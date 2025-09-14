from pydantic import BaseModel, Field


class SwapAerodromeBody(BaseModel):
    use_cache: bool = Field(False, alias="useCache", description="Whether to use cached quote if available")
    chain_id: str = Field(..., alias="chainId", description="Chain/network id as string")
    token_in: str = Field(..., alias="tokenIn", description="ERC20 token in address")
    token_out: str = Field(..., alias="tokenOut", description="ERC20 token out address")
    token_in_amount: int = Field(..., alias="tokenInAmount", description="Amount in smallest unit (wei)")
    pair_address: str = Field(..., alias="pairAddress", description="Pair (pool) contract address")
    agent_key_address: str = Field(..., alias="agentKeyAddress", description="AgentKey contract address")
    total_fee_percent: int = Field(..., alias="totalFeePercent", ge=0,
                                   description="Fee in 1/1000ths, e.g. 30 = 3%")

    class Config:
        # allow input data to use either alias names (camelCase) or field names (snake_case)
        populate_by_name = True
