import os


folder_path = os.path.join(os.path.dirname(__file__), "..", "training_data")
video_extensions = ('.mp4', '.mkv', '.avi', '.mov', '.flv', '.wmv', '.webm')


for root, dirs, files in os.walk(folder_path):
    for filename in files:
        if filename.lower().endswith(video_extensions):
            file_path = os.path.join(root, filename)
            try:
                os.remove(file_path)
                print(f"Deleted: {os.path.relpath(file_path, folder_path)}")
            except Exception as e:
                print(f"Error deleting {file_path}: {e}")

print("All video files deleted from training_data and subfolders.")
