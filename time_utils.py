from datetime import datetime, timezone

def format_time_ago(timestamp) -> str:
    """
    Handle both datetime objects and numeric timestamps
    """
    # Convert datetime objects to timestamps
    if isinstance(timestamp, datetime):
        timestamp = timestamp.timestamp()
    
    # Validate numeric timestamp
    if not timestamp or timestamp <= 0:
        return "Never"
    
    # Rest of the function remains the same
    now = datetime.now(timezone.utc)
    dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    diff = now - dt
    
    seconds = diff.total_seconds()
    
    intervals = (
        ('year', 31536000),
        ('month', 2592000),
        ('week', 604800),
        ('day', 86400),
        ('hour', 3600),
        ('min', 60),
        ('sec', 1)
    )
    
    parts = []
    for name, secs in intervals:
        value = int(seconds // secs)
        if value > 0:
            plural = 's' if value != 1 else ''
            parts.append(f"{value} {name}{plural}")
            seconds -= value * secs
            
        if len(parts) >= 2:
            break
            
    return " ".join(parts) + " ago" if parts else "Just now"