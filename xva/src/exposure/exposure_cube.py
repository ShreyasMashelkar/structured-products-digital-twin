"""
Persistent Path × Time × Trade Exposure Cube in Parquet format.

Stores NPV paths from Monte Carlo simulation for all trades.
Enables: portfolio netting, trade-level EE retrieval, XVA reuse.

Schema:
    path_id   int32  — MC path index
    time_step float32 — time in years
    trade_id  string  — trade identifier
    npv       float32 — trade NPV at (path, time)
    exposure  float32 — max(NPV, 0) at (path, time)

No external data required — written from HW1F simulation output.
Requires: pyarrow (add to requirements.txt: pyarrow>=14.0)
"""

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path
from typing import List, Optional, Dict


class ExposureCube:
    """
    Persistent Path × Time × Trade exposure cube stored in Parquet.

    Usage:
        cube = ExposureCube('data/exposure_cube.parquet')
        cube.write_paths('IRS-001', time_grid, npv_paths)
        cube.flush()
        ee = cube.compute_ee_profile('IRS-001')
    """

    SCHEMA = pa.schema([
        pa.field('path_id',   pa.int32()),
        pa.field('time_step', pa.float32()),
        pa.field('trade_id',  pa.string()),
        pa.field('npv',       pa.float32()),
        pa.field('exposure',  pa.float32()),
    ])

    def __init__(self, cube_path: str = 'data/exposure_cube.parquet'):
        self.cube_path = Path(cube_path)
        self.cube_path.parent.mkdir(parents=True, exist_ok=True)
        self._buffer: List[dict] = []
        self._buffer_rows = 0

    def write_paths(self, trade_id: str,
                    time_grid: np.ndarray,
                    npv_paths: np.ndarray):
        """
        Write simulated NPV paths for a trade to the in-memory buffer.

        Args:
            trade_id: Unique trade identifier (e.g. 'IRS-001')
            time_grid: Shape (n_steps,) — time in years
            npv_paths: Shape (n_paths, n_steps) — NPV on each path at each step
        """
        n_paths, n_steps = npv_paths.shape

        # Vectorized construction — avoids O(n_paths * n_steps) Python loop
        path_ids_2d   = np.broadcast_to(
            np.arange(n_paths, dtype=np.int32)[:, None], (n_paths, n_steps)
        )
        time_steps_2d = np.broadcast_to(
            time_grid[:n_steps][None, :], (n_paths, n_steps)
        )

        df = pd.DataFrame({
            'path_id':   path_ids_2d.ravel().astype(np.int32),
            'time_step': time_steps_2d.ravel().astype(np.float32),
            'trade_id':  trade_id,
            'npv':       npv_paths.ravel().astype(np.float32),
            'exposure':  np.maximum(npv_paths, 0.0).ravel().astype(np.float32),
        })
        self._buffer.append(df)
        self._buffer_rows += n_paths * n_steps

    def flush(self, append: bool = True):
        if not self._buffer:
            return
        df = pd.concat(self._buffer, ignore_index=True)
        table = pa.Table.from_pandas(df, schema=self.SCHEMA,
                                     preserve_index=False)
        import uuid
        if append and self.cube_path.exists():
            if self.cube_path.is_file():
                existing = pq.read_table(str(self.cube_path))
                self.cube_path.unlink()
                self.cube_path.mkdir(parents=True, exist_ok=True)
                pq.write_table(existing, self.cube_path / f"part-{uuid.uuid4().hex}.parquet")
        else:
            if self.cube_path.exists():
                if self.cube_path.is_file():
                    self.cube_path.unlink()
                else:
                    import shutil
                    shutil.rmtree(self.cube_path)
                    
        if not self.cube_path.exists():
            self.cube_path.mkdir(parents=True, exist_ok=True)
            
        pq.write_table(table, self.cube_path / f"part-{uuid.uuid4().hex}.parquet")

        self._buffer = []
        self._buffer_rows = 0

    def read_trade(self, trade_id: str) -> pd.DataFrame:
        """Read all paths for a specific trade from the cube."""
        if not self.cube_path.exists():
            raise FileNotFoundError(f"Cube not found at {self.cube_path}")
        table = pq.read_table(str(self.cube_path),
                               filters=[('trade_id', '=', trade_id)])
        return table.to_pandas()

    def compute_ee_profile(self, trade_id: str) -> pd.DataFrame:
        """
        Compute EE, EPE, PFE(95%), PFE(99%) for a trade.

        Returns DataFrame indexed by time_step.
        """
        df = self.read_trade(trade_id)
        profile = (df.groupby('time_step')['exposure']
                     .agg(EE='mean',
                          PFE_95=lambda x: np.percentile(x, 95),
                          PFE_99=lambda x: np.percentile(x, 99))
                     .reset_index()
                     .rename(columns={'time_step': 'time_years'}))
        profile['EPE'] = profile['EE']   # EPE = time-averaged EE
        return profile

    def compute_portfolio_ee(self, trade_ids: List[str]) -> pd.DataFrame:
        """
        Portfolio-level EE via netting: NPV_net = Σ NPV_trade per path.

        Proper netting requires summing NPVs before taking the max(·, 0).
        """
        if not self.cube_path.exists():
            raise FileNotFoundError(f"Cube not found at {self.cube_path}")
        table = pq.read_table(str(self.cube_path),
                               filters=[('trade_id', 'in', trade_ids)])
        df = table.to_pandas()

        net = (df.groupby(['path_id', 'time_step'])['npv']
                 .sum()
                 .reset_index()
                 .rename(columns={'npv': 'net_npv'}))
        net['net_exposure'] = np.maximum(net['net_npv'], 0)

        profile = (net.groupby('time_step')['net_exposure']
                      .agg(EE='mean',
                           PFE_95=lambda x: np.percentile(x, 95),
                           PFE_99=lambda x: np.percentile(x, 99))
                      .reset_index()
                      .rename(columns={'time_step': 'time_years'}))
        return profile

    def get_summary(self) -> Dict:
        """Cube metadata: n_trades, n_paths, n_steps, file size."""
        if not self.cube_path.exists():
            return {'exists': False}
        table = pq.read_table(str(self.cube_path))
        df = table.to_pandas()
        
        if self.cube_path.is_dir():
            size_bytes = sum(f.stat().st_size for f in self.cube_path.rglob('*') if f.is_file())
        else:
            size_bytes = self.cube_path.stat().st_size
            
        return {
            'exists':        True,
            'n_rows':        len(df),
            'n_trades':      df['trade_id'].nunique(),
            'trade_list':    df['trade_id'].unique().tolist(),
            'n_paths':       df['path_id'].nunique(),
            'n_timesteps':   df['time_step'].nunique(),
            'size_mb':       size_bytes / 1e6,
        }

    def clear(self):
        """Delete cube file (for testing/reset)."""
        if self.cube_path.exists():
            if self.cube_path.is_file():
                self.cube_path.unlink()
            else:
                import shutil
                shutil.rmtree(self.cube_path)
