"""Offline mutation checks for the repaired refusal and command-evidence gates."""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
MUTANTS=[
    ('verification page admitted','src/http_client.py',
     'return bool(title and re.search(r"please wait while your request is being verified", body))','return False'),
    ('shared cooldown ignored','src/http_client.py','if info.get("blocked_until", 0) > now:','if False:'),
    ('unexecuted diagnosis accepted','src/repair.py','if not executed:','if False:'),
    ('wrong session accepted','src/repair_bridge.py',
     'if task.findtext("t:Principals/t:Principal/t:LogonType", namespaces=ns) != "InteractiveToken":','if False:'),
]


def check(work):
    return subprocess.run([sys.executable,'-B','-m','pytest','tests/test_monitor.py','tests/test_repair_bridge.py','-q',
                           '--basetemp',str(work/'logs'/'pytest')],cwd=work,capture_output=True,text=True,encoding='utf-8',
                          env={**os.environ,'PYTHONUTF8':'1','PYTHONDONTWRITEBYTECODE':'1','PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1'},timeout=60)


def run():
    for name,rel,old,new in [('baseline',None,None,None),*MUTANTS]:
        with tempfile.TemporaryDirectory(prefix='rmon_repair_') as tmp:
            work=Path(tmp)
            for folder in ['src','tests','web']:
                shutil.copytree(ROOT/folder,work/folder,ignore=shutil.ignore_patterns('__pycache__'))
            for filename in ['main.py','save_registration.py','sync_web.py']:
                shutil.copy2(ROOT/filename,work/filename)
            (work/'logs').mkdir()
            if rel:
                path=work/rel;source=path.read_text(encoding='utf-8')
                if source.count(old)!=1:
                    raise RuntimeError('Mutation target changed: '+name)
                path.write_text(source.replace(old,new),encoding='utf-8')
            result=check(work)
            if (result.returncode==0) != (rel is None):
                print(result.stdout+result.stderr)
                raise RuntimeError('Mutation check failed: '+name)
            print(name+(': GREEN' if rel is None else ': KILLED'),flush=True)
    print('4/4 repaired protection mutants killed',flush=True)


if __name__=='__main__':
    run()
