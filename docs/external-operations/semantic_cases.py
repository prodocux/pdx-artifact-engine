"""Product-neutral executable contract examples; no runtime execution."""
import copy
import json
import semantic_validator as v
ROOT=v.ROOT
E='urn:pdx:draft:er003:support:2'
K='urn:pdx:draft:cr003:core:1'
CE='urn:pdx:draft:er003:core:1'
H=v.sha(b'synthetic-fixture')
count=0
results=[]

def check(name,fn,expected='ok'):
    global count
    try:
        out=fn(); actual='ok' if out is None else out
    except v.Invalid as exc: actual=exc.code
    assert actual==expected,(name,actual,expected)
    count+=1;results.append({'name':name,'expected':expected,'actual':actual})


def sample(s,base):
    if '$ref' in s:
        uri,_,fragment=s['$ref'].partition('#')
        doc=v.SCHEMAS[uri] if uri else v.SCHEMAS[base]
        for key in fragment.strip('/').split('/') if fragment else []: doc=doc[key]
        return sample(doc,uri or base)
    if 'const' in s:return s['const']
    if 'enum' in s:return s['enum'][0]
    if 'oneOf' in s:return sample(s['oneOf'][0],base)
    t=s.get('type');t=t[0] if isinstance(t,list) else t
    if t=='object':return {k:sample(s['properties'][k],base) for k in s.get('required',[])}
    if t=='array':
        values=[sample(s['items'],base) for _ in range(s.get('minItems',0))]
        if s.get('uniqueItems'):values=[x+str(i) if isinstance(x,str) else x for i,x in enumerate(values)]
        return values
    if t=='boolean':return False
    if t=='integer':return s.get('minimum',0)
    if t=='null':return None
    if t=='string':
        if s.get('format')=='date-time':return '2026-11-03T00:00:00Z'
        if s.get('pattern','').startswith('^[A-Z][A-Z0-9_'):return 'SAFE_ERROR'
        if '[a-f0-9]' in s.get('pattern',''):return H
        if s.get('pattern','').startswith('^-?'):return '0'
        if 'artifact://' in s.get('pattern',''):return 'artifact://example/evidence.json'
        if 'workspace://' in s.get('pattern',''):return 'workspace://example/root'
        return 'example-001' + 'x'*max(0,s.get('minLength',0)-11)
    raise AssertionError(('unsupported schema sample',s))


def artifact():
    return {'schema_version':'prodocux_opaque_artifact_v1','artifact_id':'artifact-001',
            'uri':'artifact://example/evidence.json','sha256':v.sha(b'evidence'),
            'size_bytes':8,'media_type':'application/json'}


def engine_cases():
    bases=json.loads((ROOT/'examples.json').read_text())['bases']
    activation=bases['engine_activation']
    ctx={'authenticated':True,'role':'controller','principal':'controller-001','instance_id':'instance-001',
        'authority_id':activation['authority_id'],'tenant_id':activation['tenant_id'],
        'workflow_job_id':activation['workflow_job_id'],'workflow_step_id':activation['workflow_step_id'],
        'plan_digest':activation['plan_digest'],'parent_active':True,'step_ready':True,'issuer_epoch':2,'now':'2026-11-03T00:00:05Z'}
    ctx['approval']={k:activation[k] for k in ('operation_subject_id','operation_digest','authorization_id','issuer_id')}
    ctx['approval'].update(controller_principal='controller-001',issued_at='2026-11-03T00:00:00Z',expires_at='2026-11-03T00:10:00Z',issuer_epoch=2,max_operations=1)
    ctx['approval'].update(authority_id=ctx['authority_id'],tenant_id=ctx['tenant_id'],execution_policy_digest=H)
    ctx['subject']={k:activation[k] for k in ('operation_subject_id','operation_digest')}
    ctx['subject'].update(authority_id=ctx['authority_id'],tenant_id=ctx['tenant_id'],execution_policy_digest=H)
    ctx['freshness']={'issuer_id':activation['issuer_id'],'issuer_epoch':2,'observed_at':'2026-11-03T00:00:00Z','valid_until':'2026-11-03T00:00:30Z'}
    check('E01 new activation',lambda:v.engine_activation(activation,ctx),'new')
    check('E approval foreign tenant',lambda:v.engine_activation(activation,{**ctx,'approval':{**ctx['approval'],'tenant_id':'foreign-tenant'}}),'OPERATION_BINDING_MISMATCH')
    check('E freshness foreign issuer',lambda:v.engine_activation(activation,{**ctx,'freshness':{**ctx['freshness'],'issuer_id':'foreign-issuer'}}),'AUTHORITY_FRESHNESS_UNAVAILABLE')
    exact={**ctx,'existing_idempotency':v.activation_binding(activation,ctx)}
    check('E02 exact activation',lambda:v.engine_activation(activation,exact),'existing')
    check('E exact after expiry no new submit',lambda:v.engine_activation(activation,{**exact,'now':'2026-12-01T00:00:00Z'}),'existing')
    for key in ['operation_subject_id','workflow_job_id','authorization_id','issuer_id']:
        bad={**activation,key:'different-001'}
        check('E03 changed '+key,lambda bad=bad:v.engine_activation(bad,exact),'IDEMPOTENCY_CONFLICT')
    check('E03 changed principal',lambda:v.engine_activation(activation,{**exact,'principal':'other-001'}),'IDEMPOTENCY_CONFLICT')
    check('E04 cross key exact subject',lambda:v.engine_activation({**activation,'idempotency_key':'different-key-001'},{**ctx,'existing_subject_binding':v.activation_binding(activation,ctx,False)}),'existing')
    for name,change,expected in [
        ('E05 approval used',{'authorization_used':True},'AUTHORIZATION_ALREADY_USED'),
        ('E06 subject retired',{'subject_used':True},'SUBJECT_ALREADY_BOUND'),
        ('E08 unauth',{'authenticated':False},'UNAUTHENTICATED'),
        ('E08 tenant',{'tenant_id':'other-tenant'},'RECORD_NOT_FOUND'),
        ('E09 expiry',{'now':'2026-11-04T00:00:00Z'},'AUTHORIZATION_EXPIRED'),
        ('E10 revoke',{'revoked':True},'AUTHORIZATION_REVOKED'),
        ('E09 stale freshness',{'now':'2026-11-03T00:01:00Z'},'AUTHORITY_FRESHNESS_UNAVAILABLE'),
        ('E parent not ready',{'step_ready':False},'PARENT_NOT_READY')]:
        check(name,lambda change=change:v.engine_activation(activation,{**ctx,**change}),expected)
    observation=copy.deepcopy(bases['engine_observation']);art=artifact();observation['evidence_artifact']=art
    op={k:observation[k] for k in ('operation_subject_id','operation_id','operation_digest','provider_profile_digest','account_alias','environment','provider_key_digest')}
    obsctx={**ctx,'role':'adapter','operation':op,'provenance_verified':True,
            'authorized_artifact_bytes':{art['artifact_id']:b'evidence'},'authorized_artifact_identities':{art['artifact_id']:art}}
    check('E observation valid',lambda:v.observation(observation,obsctx),'accepted')
    check('E evidence bytes tampered',lambda:v.observation(observation,{**obsctx,'authorized_artifact_bytes':{art['artifact_id']:b'evilxxxx'}}),'EVIDENCE_INVALID')
    check('E proof not verified',lambda:v.observation(observation,{**obsctx,'provenance_verified':False}),'EVIDENCE_INVALID')
    check('E18 wrong account',lambda:v.observation({**observation,'account_alias':'wrong-account'},obsctx),'OPERATION_BINDING_MISMATCH')
    check('E19 unknown after confirmed',lambda:v.observation(observation,{**obsctx,'confirmed_outcome':'confirmed_succeeded'}),'retain_confirmed')
    check('E20 conflicting confirmed',lambda:v.observation({**observation,'outcome':'confirmed_failed'},{**obsctx,'confirmed_outcome':'confirmed_succeeded'}),'conflict')
    manual={**observation,'channel':'manual_authority','outcome':'confirmed_not_executed',
        'manual_attestation':{'case_id':'case-001','attestation_artifact':art,'submitter_termination_artifact':art,'definitive_nonexecution_artifact':art}}
    manualctx={**obsctx,'role':'manual','manual_authority_fresh':True,'case_registered':'case-001','submitter_terminated':True,'definitive_nonexecution':True}
    check('E manual resolution',lambda:v.observation(manual,manualctx),'accepted')
    check('E manual termination absent',lambda:v.observation(manual,{**manualctx,'submitter_terminated':False}),'EVIDENCE_INVALID')
    check('E manual role forged',lambda:v.observation(manual,obsctx),'AUTHORITY_FORBIDDEN')
    support=v.SCHEMAS[E]['$defs']
    profile=sample(support['provider_register'],E)
    profile.update(authority_id=ctx['authority_id'],tenant_id=ctx['tenant_id'])
    profile.update(recovery_mode='query_only',lookup_proven=False,lookup_proof=None,query_deployment=None)
    pctx={**ctx,'role':'administrator'}
    check('E unproven lookup query_only',lambda:v.supporting('provider_register',profile,pctx),'PROVIDER_PROFILE_UNSUPPORTED')
    profile['recovery_mode']='manual_only'
    check('E manual_only registration',lambda:v.supporting('provider_register',profile,pctx),'valid')
    rec=sample(support['reconcile_request'],E);rec.update(operation_id=op['operation_id'],operation_digest=op['operation_digest'],provider_profile_digest=op['provider_profile_digest'])
    rec.update(authority_id=ctx['authority_id'],tenant_id=ctx['tenant_id'])
    rctx={**ctx,'role':'supervisor','operation':op,'sequence':rec['expected_sequence'],'recovery_mode':'query_only','query_calls':0,'query_execution_ms':0,'scheduling_elapsed_seconds':0}
    check('E query eligible',lambda:v.supporting('reconcile_request',rec,rctx),'valid')
    for key,value in [('query_calls',20),('query_execution_ms',600000),('scheduling_elapsed_seconds',86400)]:
        check('E21 '+key,lambda key=key,value=value:v.supporting('reconcile_request',rec,{**rctx,key:value}),'RECOVERY_BUDGET_EXHAUSTED')
    check('E manual no query budget use',lambda:v.supporting('reconcile_request',rec,{**rctx,'recovery_mode':'manual_only','query_calls':20}),'manual_required')


def routes_and_parent():
    mapping=json.loads((ROOT/'route-mapping.json').read_text())
    names=[r['operation'] for r in mapping['routes']]
    require_unique=lambda: v.require(len(names)==len(set(names)),'REQUEST_INVALID')
    check('routes unique',require_unique)
    for route in mapping['routes']:
        for field in ('request_schema','success_schema'):
            if route[field]:
                uri,_,fragment=route[field].partition('#');schema=v.SCHEMAS[uri]
                for part in fragment.strip('/').split('/') if fragment else []:schema=schema[part]
    for owner,core in [('engine',CE)]:
        expected=set(v.SCHEMAS[core]['$defs']['error']['properties']['code']['enum'])
        actual=[code for codes in mapping['errors'][owner].values() for code in codes]
        assert set(actual)==expected and len(actual)==len(set(actual)),owner
        for code in actual:
            v.shape(core+'#/$defs/error',{'schema_version':v.SCHEMAS[core]['$defs']['error']['properties']['schema_version']['const'],'request_id':'req-error-001','code':code,'message':'safe','retryable':False})
    check('routes complete error codes',lambda:None)
    check('route semantic map',lambda:v.route_mapping(mapping,mapping))
    duplicate=copy.deepcopy(mapping);duplicate['routes'][-1]=duplicate['routes'][0]
    check('route duplicated operation',lambda:v.route_mapping(duplicate,mapping),'REQUEST_INVALID')
    changed=copy.deepcopy(mapping);changed['routes'][0]['path']='/v1/wrong-path'
    check('route path drift',lambda:v.route_mapping(changed,mapping),'REQUEST_INVALID')
    fixtures=json.loads((ROOT/'shape-fixtures.json').read_text())
    plan=next(x['instance'] for x in fixtures if x['name']=='parent-plan')
    plan['plan_digest']=v.digest({k:a for k,a in plan.items() if k!='plan_digest'})
    check('parent plan semantic',lambda:v.parent_plan(plan))
    for name,mutate in [
        ('digest forged',lambda p:p.update(plan_digest=H)),
        ('duplicate step',lambda p:p['steps'].append(copy.deepcopy(p['steps'][0]))),
        ('unknown dependency',lambda p:p['steps'][0]['depends_on'].append('missing-step')),
        ('cycle',lambda p:p['steps'][0]['depends_on'].append(p['steps'][0]['workflow_step_id']))]:
        bad=copy.deepcopy(plan);mutate(bad)
        if name!='digest forged':bad['plan_digest']=v.digest({k:a for k,a in bad.items() if k!='plan_digest'})
        check('parent '+name,lambda bad=bad:v.parent_plan(bad),'OPERATION_BINDING_MISMATCH' if name=='digest forged' else 'REQUEST_INVALID')
    extplan=copy.deepcopy(plan)
    dispatch=copy.deepcopy(next(s for s in plan['steps'] if s['step_kind']=='dispatch'))
    dispatch['depends_on']=[]
    binding=sample(v.SCHEMAS[E]['$defs']['step_binding'],E)
    binding['operation_digest']=dispatch['operation_digest']
    dispatch['external_operation_binding']=binding
    extplan['steps']=[dispatch];extplan['artifact_edges']=[];extplan['budgets']['max_external_operations']=1
    extplan['plan_digest']=v.digest({k:a for k,a in extplan.items() if k!='plan_digest'})
    check('parent external plan',lambda:v.parent_plan(extplan))
    mismatch=copy.deepcopy(extplan);mismatch['steps'][0]['external_operation_binding']['operation_digest']='0'*64
    mismatch['plan_digest']=v.digest({k:a for k,a in mismatch.items() if k!='plan_digest'})
    check('parent external digest mismatch',lambda:v.parent_plan(mismatch),'OPERATION_BINDING_MISMATCH')
    state=copy.deepcopy(next(x['instance'] for x in fixtures if x['name']=='parent-state'))
    state['plan_digest']=extplan['plan_digest'];state['workflow_job_id']=extplan['workflow_job_id']
    check('parent state budget',lambda:v.parent_state(state,extplan))
    exceeded=copy.deepcopy(state);exceeded['counters']['external_calls']=extplan['budgets']['max_external_calls']+1
    check('parent state calls overflow',lambda:v.parent_state(exceeded,extplan),'RECOVERY_BUDGET_EXHAUSTED')
    effect=sample(v.SCHEMAS[E]['$defs']['receipt'],E)
    for key in ('authority_id','tenant_id','operation_subject_id','operation_digest','provider_profile_digest','authorization_id','issuer_id'):effect[key]=binding[key]
    effect.update(sequence=1,previous_receipt_digest=None,parent_terminal_receipt_artifact=None,provider_outcome='confirmed_succeeded',submission_evidence='provider_accepted',submit_permits=1)
    effect['receipt_digest']=v.digest({k:a for k,a in effect.items() if k!='receipt_digest'})
    raw=json.dumps(effect).encode();art=artifact();art.update(size_bytes=len(raw),sha256=v.sha(raw))
    rec=copy.deepcopy(next(x['instance'] for x in fixtures if x['name']=='parent-receipt'))
    rec.update(workflow_job_id=extplan['workflow_job_id'],plan_digest=extplan['plan_digest'],status='completed',artifact_edges=[],authority_records=[])
    rec.pop('terminal_error',None)
    rec['step_receipts']=[{'workflow_step_id':dispatch['workflow_step_id'],'step_kind':'dispatch','attempt_number':1,
        'status':'succeeded','execution_constraints_digest':H,'receipt_profile':'external_operation',
        'operation_allocated':True,'external_operation_receipt_artifact':art}]
    context={'authorized_artifact_bytes':{art['artifact_id']:raw},'authorized_artifact_identities':{art['artifact_id']:art}}
    check('parent confirmed receipt',lambda:v.parent_receipt(rec,extplan,context))
    effect.update(provider_outcome='unknown',reconciliation_required=True)
    effect['receipt_digest']=v.digest({k:a for k,a in effect.items() if k!='receipt_digest'})
    raw=json.dumps(effect).encode();unknown_art={**art,'size_bytes':len(raw),'sha256':v.sha(raw)}
    uncertain=copy.deepcopy(rec);uncertain['step_receipts'][0]['external_operation_receipt_artifact']=unknown_art
    context={'authorized_artifact_bytes':{art['artifact_id']:raw},'authorized_artifact_identities':{art['artifact_id']:unknown_art}}
    check('parent complete with unknown effect',lambda:v.parent_receipt(uncertain,extplan,context),'OPERATION_BINDING_MISMATCH')


def supporting_cases():
    defs=v.SCHEMAS[E]['$defs']
    ctx={'authenticated':True,'role':'issuer','principal':'issuer-principal','issuer_id':'example-001',
         'authority_id':'example-001','tenant_id':'example-001','issuer_epoch':1,'now':'2026-11-03T00:00:05Z'}
    fresh=sample(defs['issuer_freshness'],E);fresh.update(observed_at='2026-11-03T00:00:00Z',valid_until='2026-11-03T00:00:30Z')
    check('issuer freshness valid',lambda:v.supporting('issuer_freshness',fresh,ctx),'valid')
    for name,changes,context,expected in [
        ('too long',{'valid_until':'2026-11-03T00:01:00Z'},ctx,'AUTHORITY_FRESHNESS_UNAVAILABLE'),
        ('future',{'observed_at':'2026-11-03T00:00:06Z'},ctx,'AUTHORITY_FRESHNESS_UNAVAILABLE'),
        ('wrong issuer',{'issuer_id':'wrong-issuer'},ctx,'AUTHORITY_FORBIDDEN'),
        ('stale epoch',{}, {**ctx,'issuer_epoch':2},'AUTHORITY_FORBIDDEN'),
        ('backdate',{}, {**ctx,'last_observed_at':'2026-11-03T00:00:04Z'},'AUTHORITY_FRESHNESS_UNAVAILABLE')]:
        check('freshness '+name,lambda changes=changes,context=context:v.supporting('issuer_freshness',{**fresh,**changes},context),expected)
    auth=sample(defs['authorization_register'],E);auth.update(issued_at='2026-11-03T00:00:00Z',expires_at='2026-11-03T00:10:00Z')
    ctx['subject']={k:auth[k] for k in ('operation_subject_id','operation_digest','execution_policy_digest')}
    check('authorization valid',lambda:v.supporting('authorization_register',auth,ctx),'valid')
    check('authorization expired',lambda:v.supporting('authorization_register',{**auth,'expires_at':'2026-11-03T00:00:03Z'},ctx),'AUTHORIZATION_EXPIRED')
    revoke=sample(defs['authorization_revoke'],E);revoke['issuer_epoch']=2
    check('revocation monotonic',lambda:v.supporting('authorization_revoke',revoke,ctx),'valid')
    check('revocation rollback',lambda:v.supporting('authorization_revoke',{**revoke,'issuer_epoch':1},ctx),'AUTHORIZATION_REVOKED')
    projection=sample(defs['projection'],E)
    check('projection initial',lambda:v.supporting('projection',projection))
    check('projection unknown no reconcile',lambda:v.supporting('projection',{**projection,'provider_outcome':'unknown'}),'OPERATION_BINDING_MISMATCH')
    check('projection side effect without permit',lambda:v.supporting('projection',{**projection,'submission_evidence':'possibly_submitted'}),'OPERATION_BINDING_MISMATCH')
    check('projection conflict hidden',lambda:v.supporting('projection',{**projection,'conflict_count':1}),'OPERATION_BINDING_MISMATCH')
    receipt=sample(defs['receipt'],E);receipt.update(sequence=1,previous_receipt_digest=None,parent_terminal_receipt_artifact=None)
    receipt['receipt_digest']=v.digest({k:a for k,a in receipt.items() if k!='receipt_digest'})
    check('receipt initial',lambda:v.supporting('receipt',receipt))
    check('receipt changed self digest',lambda:v.supporting('receipt',{**receipt,'receipt_digest':H}),'EVIDENCE_INVALID')
    next_=copy.deepcopy(receipt);next_.update(sequence=2,previous_receipt_digest=receipt['receipt_digest'])
    next_['receipt_digest']=v.digest({k:a for k,a in next_.items() if k!='receipt_digest'})
    check('receipt append chain',lambda:v.supporting('receipt',next_,{'previous_receipt':receipt}))
    bad=copy.deepcopy(next_);bad['provider_key_digest']='0'*64;bad['receipt_digest']=v.digest({k:a for k,a in bad.items() if k!='receipt_digest'})
    check('receipt chain key replacement',lambda:v.supporting('receipt',bad,{'previous_receipt':receipt}),'OPERATION_BINDING_MISMATCH')
    # The operation digest is computed from stored specification, never caller-authoritative.
    subject=sample(defs['subject_register'],E);spec=subject['specification']
    payload=b'{"value":"1.00"}';art=artifact();art.update(size_bytes=len(payload),sha256=v.sha(payload))
    spec['payload_artifact']=art
    schema={'type':'object','required':['value'],'additionalProperties':False,'properties':{'value':{'type':'string'}}}
    spec['payload_schema_digest']=v.digest(schema)
    sctx={**ctx,'role':'controller','provider_profile_digest':spec['provider_profile_digest'],'payload_schema':schema,
          'payload_schema_id':spec['payload_schema_id'],
          'provider_profile':{k:spec[k] for k in ('provider_profile_id','provider_profile_revision','account_alias','environment','executor_identity_digest','execution_policy_digest')},
          'authorized_artifact_bytes':{art['artifact_id']:payload},'authorized_artifact_identities':{art['artifact_id']:art}}
    check('subject verified typed payload',lambda:v.supporting('subject_register',subject,sctx),'valid')
    check('subject untrusted schema',lambda:v.supporting('subject_register',subject,{**sctx,'payload_schema':{'type':'null'}}),'EVIDENCE_INVALID')
    check('subject wrong account',lambda:v.supporting('subject_register',subject,{**sctx,'provider_profile':{**sctx['provider_profile'],'account_alias':'wrong-account'}}),'OPERATION_BINDING_MISMATCH')



def run():
    engine_cases(); routes_and_parent(); supporting_cases()
    return count
