def format_time(seconds):
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f'{int(hours)}:{int(minutes):02}:{int(seconds):02}'
    elif minutes > 0:
        return f'{int(minutes):02}:{int(seconds):02}'
    else:
        return f'{int(seconds)} seconds'
