# Triton + WebUI

Demonstrate running a RAG (Retrieval Augmented Generation) pipeline on an NVIDIA Triton stack with 
an Open WebUI frontend.

# Structure

## data

- `models`: Contains the base (system agnostic) models likely downloaded from huggingface.
- `checkpoints`: The base model checkpoints translated into a TensorRT specification
- `engines`: The checkpoint specifications compiled into an engine
- `repository`: The TensorRT engine combined with a collection of Triton configuration files for specific subtasks (e.g., preprocessing, postprocessing, ensembling, etc)

## TODO

- [X] Add a build repository script that combines the engine files with the _backend example config files.
- [ ] Check if we still need a huggingface token
- [ ] Adjust the build parameters to increase the max input length
- [ ] Why is latency rather high? (I'm not looking for max throughput)
- [ ] Why is the proxy dying (run triton and proxy separately)


# Workspace layout

The root directory `~/workspace/triton-webui`.
This is what we pass to the docker container for building the optimized engines. Within the directory we have:

- `Meta-LLama-3-8B-Instruct`: base model downloaded from HF.
- `TensorRT-LLM` (v0.10.0): Just for running the correct version of `examples/llama/convert_checkpoint.py`.
- `tllm_checkpoint_1gpu_bf16`: Our original model checkpoints converted to TensorRT.
- `tmp`: where the engine files live
- `tensorrtllm_backend` (v0.10.0): Contains the 
# Components

- Base LLM is using Metas Llama3 8B Instruct model
- 

# Compilation Notes

https://developer.nvidia.com/blog/turbocharging-meta-llama-3-performance-with-nvidia-tensorrt-llm-and-nvidia-triton-inference-server/

- On Windows `--runtime=nvidia` doesn't work
- `convert_checkpoint.py` errors about `release_gc` not existing (we need to install 0.9.0)
- TensorRT-LLM v0.10.0 install torch v2.2.2 which doesn't work on the latest versions of cuda (use docker image v12.1.0)
- Make sure MIG is disabled (causes pytorch to not see the GPUs visible by nvidia-smi)
- Cleanup paths and use a venv to avoid bindings module not found issue where python is using the clone repo rather than the pip installed version
- Need to set `backend: "tensorrtllm"` in `tensorrtllm_backend/all_models/inflight_batcher_llm/tensorrt_llm/config.pbtxt`
- Need to use `nvcr.io/nvidia/tritonserver:24.05-trtllm-python-py3`
- 

OpenAPI chat endpoint seems to work
```
python3 tensorrtllm_backend/scripts/launch_triton_server.py \
    --model_repo tensorrtllm_backend/all_models/inflight_batcher_llm \
    --world_size 1 &

curl -X POST localhost:8000/v2/models/ensemble/generate -d '{
    "text_input": "What is the meaning of life?",
    "parameters": {
      "max_tokens": 128,
      "stop_words":["<|eot_id|>"]
    }
}'

/opt/tritonserver/bin/tritonopenaiserver --tokenizer_dir Meta-Llama-3-8B-Instruct

curl http://localhost:11434/v1/completions -H "Content-Type: application/json"   -d '{
    "model": "ensemble",
    "messages": [{"role": "user", "content": "What is the meaning of life?"}]
  }'


sudo docker run -d --network=host --gpus=all  -v open-webui:/app/backend/data   -e OPENAI_API_BASE_URLS="http://127.0.0.1:11434" -e WEBUI_AUTH=False  --name open-webui   ghcr.io/open-webui/open-webui:cuda
```
Unfortunately, this seems slow for now.
Weird docker networking issue and crashing, but can't find good logs.
