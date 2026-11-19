import {api} from './client.js';
export const logSetsAPI={list:()=>api('/log-sets'),create:data=>api('/log-sets',{method:'POST',body:JSON.stringify(data)})};
export const crashCasesAPI={list:()=>api('/crash-cases'),create:data=>api('/crash-cases',{method:'POST',body:JSON.stringify(data)})};
export const recoveriesAPI={list:()=>api('/recoveries'),get:id=>api('/recoveries/'+id),create:data=>api('/recoveries',{method:'POST',body:JSON.stringify(data)})};
export const mergesAPI={list:()=>api('/merges'),get:id=>api('/merges/'+id),preview:data=>api('/merges/preview',{method:'POST',body:JSON.stringify(data)}),commit:data=>api('/merges',{method:'POST',body:JSON.stringify(data)})};
