import asyncio
import logging
import os
import sys
from io import BytesIO

from pydantic import ValidationError
from flask import request, jsonify, Flask, send_file

from src.aerodrome import get_aerodrome_quote
from src.models import SwapAerodromeBody
from src.profit_cards.image_gen import build_profit_card, Agent, assets
from src.redis_utils import get_cached_swap_id, cache_swap_data

logging.basicConfig(stream=sys.stdout, level=logging.INFO)
app = Flask(__name__)

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

API_KEY = os.getenv("PROFIT_CARD_API_KEY", "supersecret123")  # fallback if unset


# Define an error handler for ValidationError
@app.errorhandler(ValidationError)
def handle_validation_error(error):
    # Return a 400 response with validation error details
    return {"status": "error", "errors": error.errors()}, 400


@app.route("/", methods=["GET"])
def healthcheck():
    return {"status": "ok"}, 200

@app.route("/swapAerodrome", methods=["POST"])
def swap_aerodrome():
    try:
        data = request.get_json()
        body = SwapAerodromeBody(**data)
    except ValidationError as e:
        return jsonify({"status": "error", "errors": e.errors()}), 400

    swap_id = f"{body.chain_id}-{body.token_in}-{body.token_out}"

    async def get_quote():
        if body.use_cache:
            if cached := await get_cached_swap_id(swap_id):
                return jsonify(cached), 200

        quote, error = await get_aerodrome_quote(body)
        if error or not quote:
            return jsonify({"status": "error", "error": error or "No quote found"}), 400

        await cache_swap_data(swap_id, quote)
        return quote, 200

    result, code = loop.run_until_complete(get_quote())

    return result, code


@app.route("/profit-card", methods=["POST"])
def profit_card():
    """
    POST JSON body like:
    {
      "name": "My Agent",
      "symbol": "AGNT",
      "profilePicture": "https://example.com/avatar.png",
      "percent": 0.15,
      "averagePrice": "1.23",
      "currentPrice": "3.45"
    }
    """
    client_key = request.headers.get("X-API-KEY")
    if client_key != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        data = request.get_json(force=True)
        agent = Agent(
            name=data["name"],
            symbol=data["symbol"],
            profilePicture=data["profilePicture"],
        )
        percent = float(data["percent"])
        avg_price = str(data.get("averagePrice", "0"))
        cur_price = str(data.get("currentPrice", "0"))
    except Exception as e:
        return jsonify({"error": f"Invalid request: {e}"}), 400

    # Generate the card
    img = build_profit_card(agent, percent, avg_price, cur_price, assets)

    # Stream back as PNG
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")

if __name__ == '__main__':
    app.run(debug=False)

