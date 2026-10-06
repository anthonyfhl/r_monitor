import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from src import repair, repair_bridge as bridge
from src.state import read_json, write_json


def task_xml():
    return f'''<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
      <Principals><Principal><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
      <Actions><Exec><Command>{Path(sys.executable).with_name('pythonw.exe')}</Command>
      <Arguments>-B -m src.repair_bridge --work</Arguments><WorkingDirectory>{bridge.PROJECT_ROOT}</WorkingDirectory></Exec></Actions>
    </Task>'''


@pytest.mark.parametrize('old,new', [('InteractiveToken','S4U'), ('LeastPrivilege','HighestAvailable'),
                                   ('--work','--work arbitrary'), ('pythonw.exe','cmd.exe')])
def test_task_drift_blocks_dispatch_before_request(tmp_path, monkeypatch, old, new):
    monkeypatch.setattr(bridge, 'BRIDGE_ROOT', tmp_path)
    clock=iter([0,bridge.MAX_AGE+1])
    monkeypatch.setattr(bridge.time,'monotonic',lambda:next(clock))
    calls=[]
    def run(*args, **kwargs):
        calls.append(args[0])
        return SimpleNamespace(returncode=0,stdout=task_xml().replace(old,new))
    monkeypatch.setattr(bridge.subprocess,'run',run)
    with pytest.raises(RuntimeError):
        bridge.request_repair('dsb_renewal','refused')
    assert len(calls)==1
    assert list(tmp_path.iterdir())==[]


def test_noninteractive_parent_uses_bridge_and_interactive_uses_same_local_gates(monkeypatch):
    calls=[]
    monkeypatch.setattr(bridge,'in_noninteractive_session',lambda:True)
    monkeypatch.setattr(bridge,'request_repair',lambda *args:(calls.append(('bridge',args)) or 'queued'))
    monkeypatch.setattr(repair,'_codex_repair_local',lambda *args:(calls.append(('local',args)) or 'verified'))
    assert repair._codex_repair('dsb_renewal','error')=='queued'
    monkeypatch.setattr(bridge,'in_noninteractive_session',lambda:False)
    assert repair._codex_repair('dsb_renewal','error')=='verified'
    assert [x[0] for x in calls]==['bridge','local']


@pytest.mark.parametrize('condition',['expired','future','interrupted','bad_source','bad_identity'])
def test_old_invalid_or_interrupted_request_never_relaunches_model(tmp_path,monkeypatch,condition):
    monkeypatch.setattr(bridge,'BRIDGE_ROOT',tmp_path)
    monkeypatch.setattr(bridge.time,'time',lambda:1000)
    monkeypatch.setattr(repair,'_codex_repair_local',lambda *args:pytest.fail('must not launch'))
    identifier='a'*32
    request={'id':identifier,'source':'dsb_renewal','error':'error','created_at':999}
    if condition=='expired':request['created_at']=1
    if condition=='future':request['created_at']=1001
    if condition=='interrupted':write_json(tmp_path/(identifier+'.started.json'),{'id':identifier})
    if condition=='bad_source':request['source']='../../other'
    if condition=='bad_identity':request['id']='b'*32
    write_json(tmp_path/(identifier+'.request.json'),request)
    assert bridge.run_pending()==0
    assert read_json(tmp_path/(identifier+'.response.json'))['id']==identifier
    assert bridge.run_pending()==0


def test_completed_request_is_never_repeated_and_original_request_stays(tmp_path,monkeypatch):
    monkeypatch.setattr(bridge,'BRIDGE_ROOT',tmp_path)
    monkeypatch.setattr(bridge.time,'time',lambda:1000)
    calls=[]
    monkeypatch.setattr(repair,'_codex_repair_local',lambda *args:(calls.append(args) or 'verified local outcome'))
    identifier='a'*32
    request_path=tmp_path/(identifier+'.request.json')
    write_json(request_path,{'id':identifier,'source':'dsb_renewal','error':'refusal','created_at':999})
    before=request_path.read_bytes()
    assert bridge.run_pending()==0
    assert bridge.run_pending()==0
    assert calls==[('dsb_renewal','refusal')]
    assert request_path.read_bytes()==before
    assert read_json(tmp_path/(identifier+'.response.json'))['outcome']=='verified local outcome'


def test_bridge_start_failure_keeps_one_pending_request_without_retries(tmp_path,monkeypatch):
    monkeypatch.setattr(bridge,'BRIDGE_ROOT',tmp_path)
    calls=[]
    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0,stdout=task_xml()) if '/Query' in command else SimpleNamespace(returncode=1,stdout='')
    monkeypatch.setattr(bridge.subprocess,'run',run)
    assert '保存待辦' in bridge.request_repair('dsb_renewal','refusal')
    assert len(calls)==2
    assert len(list(tmp_path.glob('*.request.json')))==1


def test_repair_model_exit_cannot_hide_runner_startup_failure(tmp_path):
    from src import repair
    events = tmp_path / "events.jsonl"
    events.write_text(json.dumps({"type":"item.completed","item":{"type":"command_execution","exit_code":-1,"status":"failed","aggregated_output":"Failed to create unified exec process: timed out after 15000ms connecting runner pipe-in"}}) + "\n",encoding="utf-8")
    with pytest.raises(RuntimeError, match="before execution"):
        repair._verify_command_execution(events)


def test_repair_diagnosis_requires_real_command_evidence(tmp_path):
    from src import repair
    events = tmp_path / "events.jsonl"
    events.write_text(json.dumps({"type":"item.completed","item":{"type":"agent_message","text":"Repair completed"}}) + "\n",encoding="utf-8")
    with pytest.raises(RuntimeError, match="No successful local command"):
        repair._verify_command_execution(events)
    events.write_text(json.dumps({"type":"item.completed","item":{"type":"command_execution","exit_code":0,"status":"completed","aggregated_output":"evidence read"}}) + "\n",encoding="utf-8")
    assert repair._verify_command_execution(events) == 1


def test_reading_runner_failure_fixture_is_not_a_runner_failure(tmp_path):
    path=tmp_path/'events.jsonl'
    path.write_text(json.dumps({'type':'item.completed','item':{'type':'command_execution','exit_code':0,'status':'completed',
                    'aggregated_output':'Test fixture: Failed to create unified exec process: connecting runner pipe-in'}})+'\n',encoding='utf-8')
    assert repair._verify_command_execution(path)==1


def test_exported_default_low_privilege_task_is_accepted():
    bridge.validate_task(task_xml().replace('<RunLevel>LeastPrivilege</RunLevel>', ''))
