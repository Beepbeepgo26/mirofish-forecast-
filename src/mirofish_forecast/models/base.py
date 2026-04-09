from pydantic import BaseModel, ConfigDict


class MiroFishBaseModel(BaseModel):
    """Base model for all MiroFish Forecast domain objects.

    - frozen=True: immutable after creation (thread-safe for Monte Carlo)
    - extra="forbid": catches typos in field names at validation time
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
