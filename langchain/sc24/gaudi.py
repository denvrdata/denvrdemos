# Most of this file is just a simplified version of
# https://github.com/huggingface/optimum-habana/blob/v1.14.1/examples/text-generation/text-generation-pipeline/

import copy
import os
import time
import torch

from argparse import Namespace

import habana_frameworks.torch.hpu as torch_hpu
from optimum.habana.checkpoint_utils import get_repo_root, model_is_optimized
from optimum.habana.utils import check_optimum_habana_min_version, set_seed
from transformers import AutoConfig, AutoModelForCausalLM, AutoTokenizer
from transformers.utils import check_min_version
from transformers import TextGenerationPipeline

def text_generation_settings():
    return Namespace(
        device='hpu', 
        model_name_or_path='Intel/neural-chat-7b-v3-3', 
        bf16=True,
        max_new_tokens=1024,
        max_input_tokens=2048,
        batch_size=1,
        warmup=3,
        n_iterations=5,
        local_rank=0,
        use_kv_cache=True,
        use_hpu_graphs=True,
        do_sample=True,
        num_beams=1,
        top_k=None, 
        penalty_alpha=None,
        trim_logits=False, 
        seed=27,
        profiling_warmup_steps=0,
        profiling_steps=0,
        profiling_record_shapes=False,
        prompt=None,
        assistant_model=None,
        token=None,
        model_revision='main',
        limit_hpu_graphs=False,
        ignore_eos=True,
        temperature=0.5,
        top_p=0.95,
        world_size=0,
        global_rank=0,
    )

def setup_env(args):
    # Will error if the minimal version of Transformers is not installed. Remove at your own risks.
    check_min_version("4.34.0")
    check_optimum_habana_min_version("1.9.0.dev0")
    # TODO: SW-167588 - WA for memory issue in hqt prep_model
    os.environ.setdefault("EXPERIMENTAL_WEIGHT_SHARING", "FALSE")
    from optimum.habana.transformers.modeling_utils import adapt_transformers_to_gaudi

    adapt_transformers_to_gaudi()

def setup_device(args):
    import habana_frameworks.torch.core as htcore
    return torch.device(args.device)

def setup_model(args, model_dtype, model_kwargs, logger):
    logger.info("Single-device run.")
    assistant_model = None
    model = AutoModelForCausalLM.from_pretrained(
        args.model_name_or_path, torch_dtype=model_dtype, **model_kwargs
    )
    model = model.eval().to(args.device)
    from habana_frameworks.torch.hpu import wrap_in_hpu_graph

    model = wrap_in_hpu_graph(model)
    return model, assistant_model


def setup_tokenizer(args, model, assistant_model):
    tokenizer_kwargs = { "revision": args.model_revision, "token": args.token}
    tokenizer = AutoTokenizer.from_pretrained(args.model_name_or_path, **tokenizer_kwargs)

    # Some models like GPT2 do not have a PAD token so we have to set it if necessary
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
        model.generation_config.pad_token_id = model.generation_config.eos_token_id
        if assistant_model is not None:
            assistant_model.generation_config.pad_token_id = assistant_model.generation_config.eos_token_id

    return tokenizer, model, assistant_model

def setup_generation_config(args, model, assistant_model, tokenizer):
    is_optimized = model_is_optimized(model.config)

    # Generation configuration
    generation_config = copy.deepcopy(model.generation_config)
    generation_config.max_new_tokens = args.max_new_tokens
    generation_config.use_cache = args.use_kv_cache
    generation_config.static_shapes = is_optimized and assistant_model is None
    generation_config.do_sample = args.do_sample
    generation_config.num_beams = args.num_beams
    generation_config.top_k = args.top_k
    generation_config.penalty_alpha = args.penalty_alpha
    generation_config.trim_logits = args.trim_logits
    generation_config.limit_hpu_graphs = args.limit_hpu_graphs
    generation_config.valid_sequence_lengths = None

    return generation_config


def initialize_model(args, logger):
    init_start = time.perf_counter()
    setup_env(args)
    setup_device(args)
    set_seed(args.seed)
    cache_dir = get_repo_root(args.model_name_or_path, local_rank=args.local_rank, token=args.token)
    model_dtype = torch.bfloat16

    model_kwargs = {"revision": args.model_revision, "token": args.token}
    model, assistant_model = setup_model(args, model_dtype, model_kwargs, logger)
    tokenizer, model, assistant_model = setup_tokenizer(args, model, assistant_model)
    generation_config = setup_generation_config(args, model, assistant_model, tokenizer)

    logger.info(model)
    init_end = time.perf_counter()
    # logger.info(f"Args: {args}")
    logger.info(f"device: {args.device}, n_hpu: {args.world_size}, bf16: {model_dtype == torch.bfloat16}")
    logger.info(f"Model initialization took {(init_end - init_start):.3f}s")
    return model, assistant_model, tokenizer, generation_config


class GaudiTextGenerationPipeline(TextGenerationPipeline):
    def __init__(self, args, logger):
        self.model, _, self.tokenizer, self.generation_config = initialize_model(args, logger)

        self.task = "text-generation"
        self.device = args.device

        if args.do_sample:
            self.generation_config.temperature = args.temperature
            self.generation_config.top_p = args.top_p

        self.max_padding_length = args.max_input_tokens if args.max_input_tokens > 0 else 100
        self.use_hpu_graphs = args.use_hpu_graphs
        self.profiling_steps = args.profiling_steps
        self.profiling_warmup_steps = args.profiling_warmup_steps
        self.profiling_record_shapes = args.profiling_record_shapes
        self.use_with_langchain = True
        self.generation_config.ignore_eos = False

        logger.info("Graph compilation...")

        warmup_promt = ["Here is my prompt"] * args.batch_size
        for _ in range(args.warmup):
            _ = self(warmup_promt)
        torch_hpu.synchronize()

    def __call__(self, prompt):
        use_batch = isinstance(prompt, list)

        _encode = self.tokenizer.batch_encode_plus if use_batch else self.tokenizer.encode_plus
        model_inputs = _encode(prompt, return_tensors="pt", max_length=self.max_padding_length, padding="max_length", truncation=True)

        for t in model_inputs:
            if torch.is_tensor(model_inputs[t]):
                model_inputs[t] = model_inputs[t].to(self.device)

        output = self.model.generate(
            **model_inputs,
            generation_config=self.generation_config,
            lazy_mode=True,
            hpu_graphs=self.use_hpu_graphs,
            profiling_steps=self.profiling_steps,
            profiling_warmup_steps=self.profiling_warmup_steps,
            profiling_record_shapes=self.profiling_record_shapes,
        ).cpu()

        if use_batch:
            output_text = self.tokenizer.batch_decode(output, skip_special_tokens=True)
            return [{"generated_text": unbatched_output_text} for unbatched_output_text in output_text]
        else:
            output_text = self.tokenizer.decode(output[0], skip_special_tokens=True)
            return [{"generated_text": output_text}]
