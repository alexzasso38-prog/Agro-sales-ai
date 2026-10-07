"""Authenticated API surface for the persisted sales orchestrator."""
from typing import Literal
from fastapi import Depends, Query
from fastapi.responses import JSONResponse
from . import automation as auto
from . import automation_schemas as S


def register_automation_routes(app, db, current, settings):
    @app.exception_handler(auto.AutomationError)
    async def automation_error(_request, error):
        return JSONResponse(status_code=error.status_code, content={'detail': str(error)})

    @app.get('/api/campaigns')
    def campaigns(user=Depends(current), session=Depends(db)):
        return auto.list_campaigns(session, user.producer_id)

    @app.post('/api/campaigns', status_code=201)
    def create(body: S.CampaignCreate, user=Depends(current), session=Depends(db)):
        return auto.create_campaign(session, user.producer_id, body.model_dump(), settings)

    @app.post('/api/campaigns/demo-scenario', status_code=201)
    def scenario(user=Depends(current), session=Depends(db)):
        return auto.demo_scenario(session, user.producer_id, settings)

    @app.get('/api/campaigns/{campaign_id}')
    def detail(campaign_id: int, user=Depends(current), session=Depends(db)):
        return auto.campaign_detail(session, user.producer_id, campaign_id)

    def controller(action):
        def control(campaign_id: int, user=Depends(current), session=Depends(db)):
            return auto.change_campaign(session, user.producer_id, campaign_id, action)
        return control

    for action in ('start', 'pause', 'resume', 'stop'):
        app.add_api_route(f'/api/campaigns/{{campaign_id}}/{action}', controller(action), methods=['POST'], name=f'{action}_campaign')

    @app.get('/api/campaigns/{campaign_id}/agents')
    def agents(campaign_id: int, user=Depends(current), session=Depends(db)):
        return auto.agents(session, user.producer_id, campaign_id)

    @app.get('/api/campaigns/{campaign_id}/events')
    def events(campaign_id: int, after_id: int = Query(0, ge=0), user=Depends(current), session=Depends(db)):
        return auto.events(session, user.producer_id, campaign_id, after_id=after_id)

    @app.get('/api/campaigns/{campaign_id}/tasks')
    def tasks(campaign_id: int, user=Depends(current), session=Depends(db)):
        return auto.tasks(session, user.producer_id, campaign_id)

    @app.post('/api/campaigns/{campaign_id}/agents/{agent}/{action}')
    def control_agent(campaign_id: int, agent: str, action: Literal['pause', 'resume'], user=Depends(current), session=Depends(db)):
        return auto.change_agent(session, user.producer_id, campaign_id, agent, action)

    @app.post('/api/agent-tasks/{task_id}/retry')
    def retry(task_id: int, user=Depends(current), session=Depends(db)):
        return auto.retry_task(session, user.producer_id, task_id)

    @app.post('/api/campaigns/{campaign_id}/accelerate')
    def accelerate(campaign_id: int, body: S.Accelerate, user=Depends(current), session=Depends(db)):
        return auto.accelerate(session, user.producer_id, campaign_id, body.model_dump(), settings)

    @app.post('/api/campaigns/{campaign_id}/leads/{lead_id}/simulate-response')
    def simulate_response(campaign_id: int, lead_id: int, body: S.SimulateResponse, user=Depends(current), session=Depends(db)):
        return auto.simulate_response(session, user.producer_id, campaign_id, lead_id, body.model_dump(), settings)

    @app.post('/api/campaigns/{campaign_id}/leads/{lead_id}/simulate-voice')
    def simulate_voice(campaign_id: int, lead_id: int, body: S.SimulateVoice, user=Depends(current), session=Depends(db)):
        return auto.simulate_voice(session, user.producer_id, campaign_id, lead_id, body.model_dump(), settings)

    @app.post('/api/campaigns/{campaign_id}/leads/{lead_id}/exclude')
    def exclude(campaign_id: int, lead_id: int, body: S.ExcludeLead, user=Depends(current), session=Depends(db)):
        return auto.exclude_lead(session, user.producer_id, campaign_id, lead_id, body.reason)

    @app.get('/api/human-closer')
    def handoffs(user=Depends(current), session=Depends(db)):
        return auto.handoffs(session, user.producer_id)

    @app.get('/api/human-closer/{handoff_id}')
    def handoff_detail(handoff_id: int, user=Depends(current), session=Depends(db)):
        return auto.handoff_detail(session, user.producer_id, handoff_id)

    @app.post('/api/human-closer/{handoff_id}/{action}')
    def handoff_action(handoff_id: int, action: Literal['take', 'contact', 'won', 'lost'], body: S.HandoffAction = S.HandoffAction(), user=Depends(current), session=Depends(db)):
        return auto.handoff_action(session, user.producer_id, handoff_id, action, user.id, body.note)
