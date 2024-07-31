FROM nvcr.io/nvidia/tritonserver:24.05-trtllm-python-py3

# Clone the v0.10 tensorrtllm_backend repo which includes our triton server script
RUN git clone -b v0.10.0 https://github.com/triton-inference-server/tensorrtllm_backend.git

# Install deps needed for the script
RUN pip install sentencepiece protobuf
