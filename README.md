# Setup

To install dependencies run in order:

python -m venv .venv
.\.venv\Scripts\activate  # or source .venv/bin/activate
python -m pip install -r requirements.txt


# Adding and Training face data

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

First run:

python .\tools\data_cleaner.py

This cleans the training data turning video files frames into images and removing the original video file.

Then run:

python .\tools\train_face_recognition.py {persons_name}

This trains the model on that persons face. It will be trained off the most common face in the training data.

# Testing

python .\tools\test_training_model.py {persons_name}


# Running the main script

python .\src\main.py