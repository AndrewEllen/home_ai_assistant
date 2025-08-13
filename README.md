To install dependencies run in order:

python -m venv .venv
.\.venv\Scripts\activate  # or source .venv/bin/activate
python -m pip install -r requirements.txt

Copy-Item ".\.venv\Lib\site-packages\nvidia\*\bin\*" `
          ".\.venv\Lib\site-packages\onnxruntime\capi\" -Force

python -c "import onnxruntime as ort; print(ort.get_available_providers())"
