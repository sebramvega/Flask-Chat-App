from flask import Flask, render_template, request, session, redirect, url_for
from flask_socketio import join_room, leave_room, send, SocketIO
import random
import time
from string import ascii_uppercase

# --- App bootstrap -----------------------------------------------------------
app = Flask(__name__)
app.config["SECRET_KEY"] = "hjhjsdahhds"  # TODO: read from env in production
socketio = SocketIO(app)  # auto-detect async mode (eventlet/gevent if installed)

# rooms = {
#   "ABCD": {
#       "members": 2,
#       "messages": [{"name": "Alice", "message": "Hello"}],
#       "users": {"Alice", "Bob"}
#   }
# }
rooms = {}

# per-connection (sid) send cooldown for anti-spam
last_send_ts = {}  # { sid: unix_ts }


def generate_unique_code(length: int) -> str:
    while True:
        code = "".join(random.choice(ascii_uppercase) for _ in range(length))
        if code not in rooms:
            return code


# --- HTTP routes -------------------------------------------------------------
@app.route("/", methods=["POST", "GET"])
def home():
    """
    Lobby page: user provides a display name and either joins an existing room
    or creates a new room.
    """
    session.clear()  # reset any stale session state between visits

    if request.method == "POST":
        name = request.form.get("name")
        code = request.form.get("code")
        join = request.form.get("join", False)
        create = request.form.get("create", False)

        if not name:
            return render_template(
                "home.html", error="Please enter a name.", code=code, name=name
            )
        if join is not False and not code:
            return render_template(
                "home.html", error="Please enter a room code.", code=code, name=name
            )

        # Resolve target room
        room = code
        if create is not False:
            room = generate_unique_code(4)
            rooms[room] = {"members": 0, "messages": [], "users": set()}
        elif code not in rooms:
            return render_template(
                "home.html", error="Room does not exist.", code=code, name=name
            )

        session["room"] = room
        session["name"] = name
        return redirect(url_for("room"))

    return render_template("home.html")


@app.route("/r/<code>")
def join_by_link(code):
    """
    Prefill the lobby with a room code so users can join via a shareable link.
    """
    return render_template("home.html", code=code.upper())


@app.route("/room")
def room():
    room = session.get("room")
    if room is None or session.get("name") is None or room not in rooms:
        return redirect(url_for("home"))
    return render_template(
        "room.html",
        code=room,
        name=session.get("name"),
        messages=rooms[room]["messages"],
    )


# --- Helpers -----------------------------------------------------------------
def broadcast_presence(room: str):
    """Send the current participant list to everyone in the room."""
    if room in rooms:
        users = sorted(list(rooms[room]["users"]))
        socketio.emit("presence", {"users": users, "count": len(users)}, to=room)


# --- Socket.IO events --------------------------------------------------------
@socketio.on("message")
def message(data):
    """
    Broadcast a user message to everyone in the room and append to history.
    Anti-spam: 500ms per-connection cooldown.
    """
    room = session.get("room")
    if room not in rooms:
        return

    sid = request.sid
    now = time.time()
    last = last_send_ts.get(sid, 0)
    if now - last < 0.5:
        return  # drop rapid-fire messages
    last_send_ts[sid] = now

    content = {"name": session.get("name"), "message": data["data"]}
    send(content, to=room)
    rooms[room]["messages"].append(content)
    print(f"{session.get('name')} said: {data['data']}")


@socketio.on("typing")
def typing(_data):
    """
    Notify others in the room that the current user is typing.
    """
    room = session.get("room")
    name = session.get("name")
    if room and name and room in rooms:
        socketio.emit("typing", {"name": name}, to=room, include_self=False)


@socketio.on("connect")
def connect(auth):
    room = session.get("room")
    name = session.get("name")
    if not room or not name:
        return
    if room not in rooms:
        leave_room(room)
        return

    join_room(room)
    rooms[room]["members"] += 1
    rooms[room]["users"].add(name)
    last_send_ts[request.sid] = 0
    send({"name": "System", "message": f"{name} has entered the room"}, to=room)
    broadcast_presence(room)
    print(f"{name} joined room {room}")


@socketio.on("disconnect")
def disconnect():
    room = session.get("room")
    name = session.get("name") or "Someone"
    if not room:
        return

    leave_room(room)
    last_send_ts.pop(request.sid, None)

    if room in rooms:
        rooms[room]["members"] -= 1
        if name in rooms[room]["users"]:
            rooms[room]["users"].remove(name)
        empty = rooms[room]["members"] <= 0
        if empty:
            del rooms[room]
        else:
            broadcast_presence(room)

    send({"name": "System", "message": f"{name} has left the room"}, to=room)
    print(f"{name} has left the room {room}")


# --- Dev server --------------------------------------------------------------
if __name__ == "__main__":
    socketio.run(app, debug=True, allow_unsafe_werkzeug=True)
