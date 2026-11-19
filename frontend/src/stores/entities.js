import {logSetsAPI,crashCasesAPI,recoveriesAPI,mergesAPI} from '../api/entities.js';
export const store={logs:[],cases:[],runs:[],merges:[],async refresh(){[this.logs,this.cases,this.runs,this.merges]=await Promise.all([logSetsAPI.list(),crashCasesAPI.list(),recoveriesAPI.list(),mergesAPI.list()]);}};
