import asyncio
import logging
import sys

from pydantic import ValidationError
from flask import request, jsonify, Flask

from src.aerodrome import get_aerodrome_quote
from src.models import SwapAerodromeBody
from src.redis_utils import get_cached_swap_id, cache_swap_data

logging.basicConfig(stream=sys.stdout, level=logging.INFO)
app = Flask(__name__)

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

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


if __name__ == '__main__':
    app.run(debug=False)

