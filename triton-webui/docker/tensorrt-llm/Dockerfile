FROM nvidia/cuda:12.1.0-devel-ubuntu22.04

# Clone the v0.10 TensorRT-LLM repo that we'll use the examples scripts for converting the base Llama 3 parameters to the TensorRT spec
RUN git clone -b v0.10.0 https://github.com/NVIDIA/TensorRT-LLM.git

# Clone the v0.10 tensorrtllm_backend repo for the sample model repository files and template filler script
RUN git clone -b v0.10.0 https://github.com/triton-inference-server/tensorrtllm_backend.git

# Install Python 3.10 and other TensorRT-LLM dependencies
RUN apt-get update && apt-get -y install python3.10 python3-pip openmpi-bin libopenmpi-dev

# Install the corresponding tensorrt_llm package
RUN pip3 install tensorrt_llm==0.10.0 -U --extra-index-url https://pypi.nvidia.com

COPY convert_checkpoint convert_checkpoint
COPY compile_engine compile_engine
COPY build_repository build_repository
