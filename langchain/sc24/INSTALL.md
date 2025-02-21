# Setup / Installation Notes

Install habana pytorch environment.

```
wget -nv https://vault.habana.ai/artifactory/gaudi-installer/1.16.2/habanalabs-installer.sh
chmod +x habanalabs-installer.sh
./habanalabs-installer.sh install --type dependencies
./habanalabs-installer.sh install --type pytorch
```

Setup the project environment.

```
pip install --upgrade pip
pip install "cython<3.0.0" && pip install --no-build-isolation pyyaml==5.4.1
pip install -r requirements.txt
sudo apt install bpython
```

We may need to rerun the habanalabs pytorch installer if we get:
```
>>> from transformers import TextGenerationPipeline
Traceback (most recent call last):
  File "<input>", line 1, in <module>
    from transformers import TextGenerationPipeline
  File "<frozen importlib._bootstrap>", line 1075, in _handle_fromlist
  File "/home/ubuntu/.local/lib/python3.10/site-packages/transformers/utils/import_utils.py", line 1754, in __getattr__
    module = self._get_module(self._class_to_module[name])
  File "/home/ubuntu/.local/lib/python3.10/site-packages/transformers/utils/import_utils.py", line 1766, in _get_module
    raise RuntimeError(
RuntimeError: Failed to import transformers.pipelines because of the following error (look up to see its traceback):
operator torchvision::nms does not exist
```
