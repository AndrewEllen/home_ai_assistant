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


# Setup lightbulbs/smart devices

read the tinytuya github page
https://github.com/jasonacox/tinytuya

run:
python -m tinytuya wizard

If your server is running on a subnet you can try something like:

python -m tinytuya wizard -force 192.168.1.0/24 192.168.0.0/24

although your server may need a persistent static route setup.


# Setup microphone

run python .\tools\fetch_microphone.py

This will return the microphone index. Next just set the device in the voice_thread on main.py

# Running the main script

python .\src\main.py