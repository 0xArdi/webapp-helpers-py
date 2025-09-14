import asyncio
import json
from pathlib import Path

from eth_utils import to_checksum_address
from sugar import get_async_chain, BaseChainCommon
from sugar.token import Token
from web3 import AsyncWeb3, AsyncHTTPProvider, Web3

from src.chains import CHAIN_MAP
from src.models import SwapAerodromeBody

aerodrome_factory_path = Path(__file__).parent / "abis" / "AerodromeFactory.json"
aerodrome_router_path = Path(__file__).parent / "abis" / "AerodromeRouter.json"
aerodrome_pair_path = Path(__file__).parent / "abis" / "UniswapV2Pair.json"


with open(aerodrome_factory_path) as f:
    aerodrome_factory_abi = json.load(f)

with open(aerodrome_router_path) as f:
    aerodrome_router_abi = json.load(f)

with open(aerodrome_pair_path) as f:
    aerodrome_pair_abi = json.load(f)

ERC20_ABI = [
    {"constant": True, "inputs": [], "name": "symbol", "outputs": [{"name": "", "type": "string"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
]

async def get_token(chain_id: str, token_address: str) -> Token:
    rpc_uri = CHAIN_MAP[str(chain_id)]["rpc_uri"]
    w3 = AsyncWeb3(AsyncHTTPProvider(rpc_uri))
    token_address = to_checksum_address(token_address)
    contract = w3.eth.contract(address=token_address, abi=ERC20_ABI)

    symbol, decimals = await asyncio.gather(
        contract.functions.symbol().call(),
        contract.functions.decimals().call(),
    )
    return Token(
        chain_id=chain_id,
        chain_name="Base",
        token_address=token_address,
        symbol=symbol,
        decimals=decimals,
        listed=False,
    )


async def get_aerodrome_quote(body: SwapAerodromeBody) -> tuple[dict | None, str | None]:
    """
    Get a sell-tax aware quote on Aerodrome.

    Returns (quote_dict | None, error_message | None)
    """
    factory_address = CHAIN_MAP[str(body.chain_id)]["factory_address"]

    async with get_async_chain(
        chain_id=body.chain_id,
        rpc_uri=CHAIN_MAP[str(body.chain_id)]["rpc_uri"],
    ) as chain:
        # Fetch token metadata (native ETH if zero address)
        ZERO_ADDR = "0x0000000000000000000000000000000000000000"

        # Decide which tokens actually need fetching
        in_is_zero = body.token_in.lower() == ZERO_ADDR
        out_is_zero = body.token_out.lower() == ZERO_ADDR

        coros = []
        if not in_is_zero:
            coros.append(get_token(chain_id=body.chain_id, token_address=body.token_in))
        if not out_is_zero:
            coros.append(get_token(chain_id=body.chain_id, token_address=body.token_out))

        # Run the remaining coroutines concurrently (if any)
        results = await asyncio.gather(*coros) if coros else []

        # Assign results back in correct order
        token_in_obj = chain.eth if in_is_zero else results[0 if not in_is_zero else None]
        token_out_obj = chain.eth if out_is_zero else results[-1 if not out_is_zero else None]

        is_sell = token_in_obj.token_address.lower() == body.agent_key_address.lower()
        quote = await chain.get_quote(
            from_token=token_in_obj,
            to_token=token_out_obj,
            amount=int(body.token_in_amount),
        )
        if not quote:
            return None, "No quote found"

        lp = quote.path[0][0].lp
        token_path = [(token_in_obj.wrapped_token_address or token_in_obj.token_address).lower()]
        for pool, _ in quote.path:
            # pool.token0_address and pool.token1_address are strings
            if token_path[-1] == pool.token0_address.lower():
                # we entered as token0, next token is token1
                token_path.append(pool.token1_address.lower())
            elif token_path[-1] == pool.token1_address.lower():
                # we entered as token1, next token is token0
                token_path.append(pool.token0_address.lower())
            else:
                raise ValueError(f"token_in {token_path[-1]} not found in pool {pool.lp}")

        factory = chain.web3.eth.contract(address=factory_address,
                                          abi=aerodrome_factory_abi)
        swap_path = []
        for i in range(len(token_path) - 1):
            swap_path.append({
                "from": Web3.to_checksum_address(token_path[i]),
                "to": Web3.to_checksum_address(token_path[i + 1]),
                "stable": False,
                "factory": Web3.to_checksum_address(factory.address),
            })

        if not is_sell:
            return {
                "quote": str(quote.amount_out),
                "path": swap_path,
            }, None


        if lp.lower() != body.pair_address.lower():
            return {
                "quote": str(quote.amount_out),
                "path": swap_path,
            }, None

        fee_bps = await factory.functions.getFee(lp, False).call()
        amount_in_wei = int(quote.amount_in)
        fee = int((amount_in_wei * int(body.total_fee_percent)) / 1000)

        router = chain.web3.eth.contract(address=chain.router.address,
                                         abi=aerodrome_router_abi)
        fee_input, fee_output = await router.functions.getAmountsOut(int(fee), [
            {
                "from": Web3.to_checksum_address(body.agent_key_address),
                "to": Web3.to_checksum_address(token_path[1]),
                "stable": False,
                "factory": Web3.to_checksum_address(factory.address),
            }
        ]).call()

        pair = chain.web3.eth.contract(address=Web3.to_checksum_address(body.pair_address), abi=aerodrome_pair_abi)
        reserves = await pair.functions.getReserves().call()
        token0 = (await pair.functions.token0().call()).lower()

        is_ak_token0 = token0 == body.agent_key_address.lower()

        base_reserve = reserves[1] if is_ak_token0 else reserves[0]
        token_reserve = reserves[0] if is_ak_token0 else reserves[1]

        remaining = amount_in_wei - fee
        fee_input -= (fee_input * fee_bps) // 10000
        remaining -= (remaining * fee_bps) // 10000
        real_base_amount = (remaining * base_reserve) / (token_reserve + remaining)

        final_quote = quote.amount_out
        if len(token_path) > 2:
            _, final_quote = await router.functions.getAmountsOut(int(real_base_amount), swap_path[1:]).call()

        print(final_quote or quote)
        return {
            "quote": str(final_quote),
            "path": swap_path,
        }, None




