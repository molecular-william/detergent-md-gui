import numpy as np


def add_solvent(solute, box, spacing=.47, seed=0, ions=0):
 sol=np.asarray(solute,float); box=np.asarray(box,float); rng=np.random.default_rng(seed)
 grid=np.stack(np.meshgrid(*[np.arange(spacing/2,x,spacing) for x in box],indexing='ij'),-1).reshape(-1,3)
 if len(sol): grid=grid[np.min(np.linalg.norm(grid[:,None,:]-sol[None,:,:],axis=2),axis=1)>.35]
 if ions: grid=rng.choice(grid,size=min(ions,len(grid)),replace=False)
 return grid
