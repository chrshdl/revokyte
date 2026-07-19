import json

import matplotlib.pyplot as plt


def plot():
    # Load the track data
    try:
        with open("tracks.json", "r") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(
            "Error: 'tracks.json' not found. Please ensure it is in the same directory."
        )
        return

    # Create the figure
    plt.figure(figsize=(10, 8))

    # Iterate over every track in the JSON, plotting its bounding box and
    # start/finish gate (this DB no longer stores a recorded racing line —
    # see CLAUDE.md's Track Database section).
    for track_id, track_data in data.items():
        name = track_data.get("name", f"Track {track_id}")
        gate = track_data.get("gate")
        bounds = track_data.get("bounds")

        if bounds is not None:
            box_x = [bounds["min_x"], bounds["max_x"], bounds["max_x"], bounds["min_x"], bounds["min_x"]]
            box_z = [bounds["min_z"], bounds["min_z"], bounds["max_z"], bounds["max_z"], bounds["min_z"]]
            (line,) = plt.plot(box_x, box_z, label=name, linestyle="--", alpha=0.5)

        if gate is not None:
            p1, p2 = gate["p1"], gate["p2"]
            color = line.get_color() if bounds is not None else None
            plt.plot([p1["x"], p2["x"]], [p1["z"], p2["z"]], marker="o", linewidth=3, color=color)

    # Format the plot for easy overlap checking
    plt.axis("equal")  # Ensures 1:1 aspect ratio so the track shape is accurate
    plt.xlabel("X")
    plt.ylabel("Z")
    plt.title("Track Layouts - Overlap Check")
    plt.legend()
    plt.grid(True)

    # Show the plot
    plt.show()


if __name__ == "__main__":
    plot()
