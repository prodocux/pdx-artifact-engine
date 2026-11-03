// Contract tooling only. No runtime imports, provider calls or external writes.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';

const root=path.dirname(fileURLToPath(import.meta.url));

const fail=()=>{throw new Error('IJSON_INVALID');};
function validString(s){
  for(let i=0;i<s.length;i++){
    const n=s.charCodeAt(i);
    if(n>=0xd800&&n<=0xdbff){const next=s.charCodeAt(++i);if(!(next>=0xdc00&&next<=0xdfff))fail();}
    else if(n>=0xdc00&&n<=0xdfff)fail();
  }
}
export function parseStrict(raw){
  let i=0;
  const ws=()=>{while(/[\x20\x09\x0a\x0d]/.test(raw[i]??'!'))i++;};
  function string(){
    const start=i++;let escaped=false;
    while(i<raw.length){const c=raw[i++];if(!escaped&&c==='"'){const s=JSON.parse(raw.slice(start,i));validString(s);return s;}if(!escaped&&c==='\\')escaped=true;else escaped=false;}
    fail();
  }
  function value(depth=0){
    if(depth>64)fail();
    ws();const c=raw[i];
    if(c==='"')return string();
    if(c==='{'){
      i++;ws();const out=Object.create(null);if(raw[i]==='}'){i++;return out;}
      while(i<raw.length){ws();if(raw[i]!=='"')fail();const k=string();ws();if(raw[i++]!==':')fail();if(Object.hasOwn(out,k))fail();out[k]=value(depth+1);ws();const sep=raw[i++];if(sep==='}')return out;if(sep!==',')fail();}fail();
    }
    if(c==='['){i++;ws();const out=[];if(raw[i]===']'){i++;return out;}while(i<raw.length){out.push(value(depth+1));ws();const sep=raw[i++];if(sep===']')return out;if(sep!==',')fail();}fail();}
    for(const [token,v] of [['true',true],['false',false],['null',null]])if(raw.slice(i,i+token.length)===token){i+=token.length;return v;}
    const number=raw.slice(i).match(/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/);
    if(!number)fail();i+=number[0].length;const n=Number(number[0]);if(!Number.isFinite(n))fail();
    if(!/[.eE]/.test(number[0])&&!Number.isSafeInteger(n))fail();return n;
  }
  const result=value();ws();if(i!==raw.length)fail();return result;
}
export function jcs(x){
  if(x===null||typeof x==='boolean')return JSON.stringify(x);
  if(typeof x==='number'){if(!Number.isFinite(x))fail();return JSON.stringify(x);}
  if(typeof x==='string'){validString(x);return JSON.stringify(x);}
  if(Array.isArray(x))return '['+x.map(jcs).join(',')+']';
  if(typeof x!=='object')fail();
  return '{'+Object.keys(x).sort().map(k=>{validString(k);return JSON.stringify(k)+':'+jcs(x[k]);}).join(',')+'}';
}
const vectors=JSON.parse(fs.readFileSync(path.join(root,'canonical-vectors.json'),'utf8'));
const parity=[];
for(const v of vectors.positive){const canonical=jcs(parseStrict(v.raw));parity.push({name:v.name,utf8_hex:Buffer.from(canonical).toString('hex'),sha256:crypto.createHash('sha256').update(canonical).digest('hex')});}
for(const v of vectors.negative){let rejected=false;try{jcs(parseStrict(v.raw));}catch{rejected=true;}if(!rejected)throw new Error('NEGATIVE_ACCEPTED '+v.name);}

const dep=process.env.PDX_AJV_MODULE_ROOT;
if(!dep)throw new Error('Set PDX_AJV_MODULE_ROOT to an existing ajv + ajv-formats dependency root');
const req=createRequire(path.resolve(dep,'package.json'));
const Ajv=req('ajv/dist/2020').default;const formats=req('ajv-formats').default;
const ajv=new Ajv({strict:true,allErrors:true});formats(ajv);
const schemaMap=new Map();
function readDir(dir){for(const entry of fs.readdirSync(dir,{withFileTypes:true})){const p=path.join(dir,entry.name);if(entry.isDirectory())readDir(p);else if(p.endsWith('.json')){const s=JSON.parse(fs.readFileSync(p,'utf8'));if(s.$id)schemaMap.set(s.$id,s);}}}
if(fs.existsSync(path.join(root,'dependencies')))readDir(path.join(root,'dependencies'));
readDir(path.join(root,'schemas'));
for(const s of schemaMap.values())ajv.addSchema(s);
let schemas=0;
for(const f of fs.readdirSync(path.join(root,'schemas'))){const s=JSON.parse(fs.readFileSync(path.join(root,'schemas',f),'utf8'));ajv.getSchema(s.$id);schemas++;}
const fixtures=JSON.parse(fs.readFileSync(path.join(root,'shape-fixtures.json'),'utf8'));
for(const test of fixtures){const validate=ajv.compile({$ref:test.schema});if(validate(test.instance)!==test.valid)throw new Error('SHAPE '+test.name+' '+JSON.stringify(validate.errors));}
console.log(JSON.stringify({schemas,shape_cases:fixtures.length,positive:parity,negative:vectors.negative.length,ajv:req('ajv/package.json').version,formats:req('ajv-formats/package.json').version}));
