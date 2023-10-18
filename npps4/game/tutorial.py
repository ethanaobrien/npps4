from .. import idol
from .. import util
from ..idol import error
from ..idol.system import tutorial
from ..idol.system import user

import pydantic


class TutorialProgressRequest(pydantic.BaseModel):
    tutorial_state: int


@idol.register("/tutorial/progress", batchable=False)
async def tutorial_progress(
    context: idol.SchoolIdolUserParams, request: TutorialProgressRequest
) -> idol.core.DummyModel:
    current_user = await user.get_current(context)
    if current_user.tutorial_state == -1:
        raise error.IdolError(detail="Tutorial already finished")

    if current_user.tutorial_state == 0 and request.tutorial_state == 1:
        await tutorial.phase1(context, current_user)
        return idol.core.DummyModel()
    elif current_user.tutorial_state == 1 and request.tutorial_state == 2:
        await tutorial.phase2(context, current_user)
        return idol.core.DummyModel()
    elif current_user.tutorial_state == 2 and request.tutorial_state == 3:
        await tutorial.phase3(context, current_user)
        return idol.core.DummyModel()
    elif current_user.tutorial_state == 3 and request.tutorial_state == -1:
        await tutorial.finalize(context, current_user)
        return idol.core.DummyModel()

    raise error.IdolError(detail=f"Unknown state, u {current_user.tutorial_state} r {request.tutorial_state}")


@idol.register("/tutorial/skip", batchable=False)
async def tutorial_skip(context: idol.SchoolIdolUserParams) -> idol.core.DummyModel:
    current_user = await user.get_current(context)
    if current_user.tutorial_state == -1:
        raise error.IdolError(detail="Tutorial already finished")

    if current_user.tutorial_state >= 0:
        await tutorial.phase1(context, current_user)
    if current_user.tutorial_state >= 1:
        await tutorial.phase2(context, current_user)
    if current_user.tutorial_state >= 2:
        await tutorial.phase3(context, current_user)
    if current_user.tutorial_state >= 3:
        await tutorial.finalize(context, current_user)

    return idol.core.DummyModel()
