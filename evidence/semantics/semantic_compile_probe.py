import ast
import asyncio
import json
import os
import sys
from pathlib import Path
os.environ['SLAYER_USAGE_REPORTING']='off'
import duckdb
from slayer.core.models import Column, ModelJoin, SlayerModel
from slayer.core.query import SlayerQuery
from slayer.engine.syntax import parse_expr, Literal, Cmp
from _upstream_engine_helpers import seeded_exec_engine
from slayer.embeddings import client
client.is_available=lambda:False
OUT=Path(__file__).parent

def seed(path):
    c=duckdb.connect(path)
    c.execute("CREATE TABLE cells(id INTEGER,municipality VARCHAR,period_start DATE,report_year INTEGER)")
    c.execute("INSERT INTO cells VALUES (1,'A',DATE '2024-01-01',2024),(2,'A',DATE '2025-01-01',2025),(3,'B',DATE '2024-01-01',2024),(4,'B',DATE '2025-01-01',2025)")
    c.execute("CREATE TABLE staff(id INTEGER,cell_id INTEGER,education VARCHAR,stock INTEGER)")
    c.execute("INSERT INTO staff VALUES(1,1,'p',10),(2,1,'q',20),(3,2,'p',11),(4,2,'q',22),(5,4,'p',5),(6,4,'q',15)")
    c.execute("CREATE TABLE population(id INTEGER,cell_id INTEGER,n INTEGER)")
    c.execute("INSERT INTO population VALUES(1,1,100),(2,2,110),(3,3,200),(4,4,200)")
    c.execute("CREATE TABLE vehicles(id INTEGER,cell_id INTEGER,kind VARCHAR,n INTEGER)")
    c.execute("INSERT INTO vehicles VALUES(1,1,'car',30),(2,1,'moto',10),(3,2,'car',33),(4,2,'moto',11),(5,3,'car',50),(6,3,'moto',20),(7,4,'car',60),(8,4,'moto',30)")
    c.close()

def col(n,t='number',**kw):return Column(name=n,type=t,**kw)
def models():
    out=[SlayerModel(name='cells',data_source='test',sql_table='cells',columns=[col('id',primary_key=True),col('municipality','string'),col('period_start','date'),col('report_year')],default_time_dimension='period_start')]
    for name,more in [('staff',[col('education','string'),col('stock')]),('population',[col('n')]),('vehicles',[col('kind','string'),col('n')])]:
        out.append(SlayerModel(name=name,data_source='test',sql_table=name,columns=[col('id',primary_key=True),col('cell_id'),*more],joins=[ModelJoin(target_model='cells',join_pairs=[['cell_id','id']],cardinality='many_to_one')]))
    return out

async def main():
    results=[]
    annual='sum(staff.stock, partition_by=[municipality, year(period_start)])'
    ratio='1000 * sum(vehicles.n) / nullif(sum(population.n, partition_by=[municipality, year(period_start)]), 0)'
    cases=[('annual_mean_and_coverage',dict(source_model='cells',dimensions=['municipality'],filters=['report_year >= 2024','report_year <= 2025'],measures=[{'name':'mean','formula':f'avg({annual})'},{'name':'coverage','formula':f'count({annual})'}],to_many_handling='error')),
           ('shared_root_period_compare',dict(source_model='cells',dimensions=['municipality','vehicles.kind'],time_dimensions=[{'dimension':'period_start','granularity':'year','date_range':['2025-01-01','2025-12-31']}],measures=[{'name':'current','formula':ratio},{'name':'previous','formula':f"time_shift({ratio}, -1, 'year')"},{'name':'change','formula':f"({ratio}) - time_shift({ratio}, -1, 'year')"}],to_many_handling='error'))]
    async with seeded_exec_engine(dialect='duckdb',seed=seed,models=models()) as (engine,db):
        for name,body in cases:
            try:
                result=await engine.execute(SlayerQuery.model_validate(body))
                results.append({'name':name,'query':body,'status':'ok','data':result.data,'warnings':[w.model_dump(mode='json') for w in result.warnings],'sql':result.sql})
            except Exception as e:
                results.append({'name':name,'query':body,'status':'error','error':repr(e)})
    for value in ["O'Brien", "x') or True or ('", 'a\\b\nAND NULL', '__slayer_ OVER(', 'A"B']:
        tree=ast.Compare(left=ast.Name(id='education',ctx=ast.Load()),ops=[ast.Eq()],comparators=[ast.Constant(value=value)])
        formula=ast.unparse(ast.fix_missing_locations(tree))
        bound=parse_expr(formula)
        assert isinstance(bound,Cmp) and isinstance(bound.right,Literal) and bound.right.value==value
        results.append({'name':'literal_roundtrip','value':value,'formula':formula,'status':'ok'})
    (OUT/'semantic_compile_probe_results.json').write_text(json.dumps(results,indent=2,default=str))
    print(json.dumps([{k:v for k,v in x.items() if k not in ('sql','query')}for x in results],indent=2,default=str))

loop=asyncio.new_event_loop()
asyncio.set_event_loop(loop)
def pulse():loop.call_later(.05,pulse)
loop.call_later(.05,pulse)
try:loop.run_until_complete(main())
finally:
    loop.run_until_complete(loop.shutdown_asyncgens())
    loop.run_until_complete(loop.shutdown_default_executor())
    loop.close()
