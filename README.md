# Setup

To install dependencies run in order:

python -m venv .venv
.\.venv\Scripts\activate  # or source .venv/bin/activate
python -m pip install -r requirements.txt


# Train face

Place training data inside training_data with the following folder structure:

training_data
├── {persons_name_1}
│   ├── {picture1}.jpg
|   ├── {picture2}.jpeg
|   ├── {picture3}.png
|   └── ...
└── {persons_name_2}
    ├── {picture1}.jpg
    ├── {picture2}.jpeg
    ├── {picture3}.png
    └── ...

python .\tools\train_face_recognition.py {persons_name}
