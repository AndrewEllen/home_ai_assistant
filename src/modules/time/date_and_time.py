import time

def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"

def period_of_day(h_24: int) -> str:
    if h_24 < 12:
        return "in the morning"
    elif h_24 < 18:
        return "in the afternoon"
    else:
        return "in the evening"

def fetch_time():
    h_24 = int(time.strftime("%H"))
    h_12 = int(time.strftime("%I"))
    m = int(time.strftime("%M"))
    am_pm = time.strftime("%p").lower()

    if m == 15:
        return f"It is quarter past {h_12} {period_of_day(h_24)}"
    elif m == 30:
        return f"It is half past {h_12} {period_of_day(h_24)}"
    elif m == 45:
        return f"It is quarter to {(h_12 % 12) + 1} {period_of_day(h_24)}"
    else:
        return f"It is {h_12}:{m:02d}{am_pm}"

def day_month():
    d = int(time.strftime("%d"))
    return f"It is the {ordinal(d)} of {time.strftime('%B')}"

def day_month_year():
    d = int(time.strftime("%d"))
    return f"It is the {ordinal(d)} of {time.strftime('%B %Y')}"

def build_time_message(msg: str):
    msg_lower = msg.lower()

    if "time" in msg_lower:
        return fetch_time()
    elif "day" in msg_lower and "month" in msg_lower and "year" in msg_lower:
        return day_month_year()
    elif "day" in msg_lower and "month" in msg_lower:
        return day_month()
    elif "day" in msg_lower and "year" in msg_lower:
        d = int(time.strftime("%d"))
        return f"It is the {ordinal(d)} of {time.strftime('%Y')}"
    elif "day" in msg_lower:
        return day_month()
    elif "month" in msg_lower and "year" in msg_lower:
        return f"It is {time.strftime('%B %Y')}"
    elif "month" in msg_lower:
        return f"It is {time.strftime('%B')}"
    elif "year" in msg_lower:
        return f"It is {time.strftime('%Y')}"
    else:
        return "I don't understand the request."



if __name__ == "__main__":
  print(build_time_message("what day is it"))
  print(build_time_message("what day of the month is it"))
  print(build_time_message("what day month year is it"))
  print(build_time_message("what day month and year is it"))
  print(build_time_message("what time is it"))
  print(build_time_message("what time of day is it"))
  print(build_time_message("what month year is it"))
  print(build_time_message("what year is it"))
