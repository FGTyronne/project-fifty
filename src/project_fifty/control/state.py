from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from project_fifty.domain.models import ExperimentMode


class ControlState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: ExperimentMode = ExperimentMode.NORMAL
    kill_switch_active: bool = False

    def transition_mode(self, next_mode: ExperimentMode, *, automatic: bool = False) -> None:
        if self.mode == ExperimentMode.DEAD and next_mode != ExperimentMode.DEAD:
            raise ValueError("DEAD mode is terminal for this experiment")
        self.mode = next_mode
