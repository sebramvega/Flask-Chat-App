from flask import Flask, render_template, request, session, redirect, url_for
from flask_socketio import join_room, leave_room, send, SocketIO
import random
from string import ascii_uppercase

# --- App bootstrap -----------------------------------------------------------
# Minimal Flask + Socket.IO chat app.
# Uses in-memory storage for rooms/messages (fine for demos, not for prod).
app = Flask(__name__)
app.config["SECRET_KEY"] = "hjhjsdahhds"  # TODO: read from env in production
socketio = SocketIO(app)  # auto-detects best async mode (eventlet/gevent if installed)

# rooms = {
#   "ABCD": {
#       "members": 2,
#       "messages": [{"name": "Alice", "message": "Hello"}]
#   }
# }
rooms = {}


def generate_unique_code(length: int) -> str:
    """
    Generate a short, human-friendly uppercase code that is unique among active rooms.

    Collisions are extremely unlikely for small loads; we re-roll on collision.
    In production, consider a central store (DB/Redis) if you need durability.
    """
    while True:
        code = "".join(random.choice(ascii_uppercase) for _ in range(length))
        if code not in rooms:
            return code


# --- HTTP routes -------------------------------------------------------------
@app.route("/", methods=["POST", "GET"])
def home():
    """
    Lobby page: user provides a display name and either:
      - joins an existing room (with code), or
      - creates a new room (receives a generated code).
    """
    session.clear()  # reset any stale session state between visits

    if request.method == "POST":
        name = request.form.get("name")
        code = request.form.get("code")
        join = request.form.get("join", False)
        create = request.form.get("create", False)

        # Basic form validation with friendly error messages
        if not name:
            return render_template(
                "home.html", error="Please enter a name.", code=code, name=name
            )

        if join is not False and not code:
            return render_template(
                "home.html", error="Please enter a room code.", code=code, name=name
            )

        # Resolve the target room (either new or existing)
        room = code
        if create is not False:
            room = generate_unique_code(4)
            rooms[room] = {"members": 0, "messages": []}
        elif code not in rooms:
            return render_template(
                "home.html", error="Room does not exist.", code=code, name=name
            )

        # Persist minimal identity & destination in the signed session cookie
        session["room"] = room
        session["name"] = name

        return redirect(url_for("room"))

    # GET request -> plain lobby
    return render_template("home.html")


@app.route("/room")
def room():
    """
    Chat room page: renders existing history and bootstraps the Socket.IO client.
    Guard against direct navigation without a valid session.
    """
    room = session.get("room")
    if room is None or session.get("name") is None or room not in rooms:
        return redirect(url_for("home"))

    # Pass current name for client-side "me" styling
    return render_template(
        "room.html",
        code=room,
        name=session.get("name"),
        messages=rooms[room]["messages"],
    )


# --- Socket.IO events --------------------------------------------------------
@socketio.on("message")
def message(data):
    """
    Broadcast a user message to everyone in the room and append to history.
    The client sends: {"data": "<text>"}.
    """
    room = session.get("room")
    if room not in rooms:
        return  # stale session; nothing to do

    content = {"name": session.get("name"), "message": data["data"]}
    send(content, to=room)  # real-time fanout
    rooms[room]["messages"].append(content)  # lightweight persistence (in-memory)
    print(f"{session.get('name')} said: {data['data']}")


@socketio.on("connect")
def connect(auth):
    """
    When a websocket connects, attach it to the session's room if valid.
    Send a lightweight system message so the UI can show presence changes.
    """
    room = session.get("room")
    name = session.get("name")
    if not room or not name:
        return  # do not join without identity
    if room not in rooms:
        leave_room(room)
        return

    join_room(room)
    send({"name": name, "message": "has entered the room"}, to=room)
    rooms[room]["members"] += 1
    print(f"{name} joined room {room}")


@socketio.on("disconnect")
def disconnect():
    """
    On disconnect, leave the room, decrement membership, and prune empty rooms.
    """
    room = session.get("room")
    name = session.get("name") or "Someone"
    if not room:
        return

    leave_room(room)

    if room in rooms:
        rooms[room]["members"] -= 1
        empty = rooms[room]["members"] <= 0
        if empty:
            # Free memory: ephemeral rooms are deleted when the last member leaves.
            del rooms[room]

    send({"name": name, "message": "has left the room"}, to=room)
    print(f"{name} has left the room {room}")


# --- Dev server --------------------------------------------------------------
if __name__ == "__main__":
    # For local development only. In production, use eventlet/gevent or ASGI server.
    socketio.run(app, debug=True, allow_unsafe_werkzeug=True)
