import json
from fastapi import APIRouter,Depends
from fastapi.responses import Response
from src.config.database import get_db
from src.utils.security import current_user,editor
from src.schemas.business import TrialInput
from src.services import trials
router=APIRouter()
@router.get('/trials')
def listing(db=Depends(get_db),user=Depends(current_user)): return [trials.serialize_batch(b) for b in trials.list_batches(db)]
@router.post('/trials',status_code=201)
def create(data:TrialInput,db=Depends(get_db),user=Depends(editor)): return trials.serialize_detail(db,trials.create_batch(db,data,user))
@router.get('/trials/{id}')
def detail(id:int,db=Depends(get_db),user=Depends(current_user)): return trials.serialize_detail(db,trials.get_batch(db,id))
@router.post('/trials/{id}/reveal')
def reveal(id:int,db=Depends(get_db),user=Depends(editor)): return trials.serialize_detail(db,trials.reveal_batch(db,id))
@router.get('/trials/{id}/export')
def export(id:int,db=Depends(get_db),user=Depends(current_user)):
    batch=trials.get_batch(db,id)
    content=trials.serialize_detail(db,batch)
    return Response(json.dumps(content,ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="trial-batch-{id}.json"'})
