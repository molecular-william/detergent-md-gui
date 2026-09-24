"""Molecule-class naming for coarse-grained workflow runs."""
from __future__ import annotations

from dataclasses import dataclass
from ...models.molecules.aa import cg_residue_name


# Set to True once the six shipped shell scripts consume MOLECULE_TYPE,
# INITIAL_ITP, FINAL_ITP and AA_REFERENCE_DIR. Flip by running the shipped
# migrator (dashboard/execution/scripts/migrate_cg_naming.py) and confirming
# --check reports "All six CG scripts are migrated."
SHELL_SCRIPTS_READ_ENV = True


@dataclass(frozen=True)
class CGNames:
    """Resolved coarse-grained naming for one prepared run."""

    residue_name: str
    initial_itp: str
    final_itp: str

    @classmethod
    def for_snapshot(cls, snapshot) -> "CGNames":
        residue = cg_residue_name(snapshot)
        # GRO stores residue names in a five-character field.  Imported AA
        # records commonly have a long display ID (for example, Maltose) but
        # retain the source topology's short residue name (LIG1).
        if not residue or len(residue) > 5:
            raise ValueError(
                f"Molecule {snapshot['id']!r} needs metadata.cg_molecule_type "
                "or molecule_type no longer than five characters for GRO output"
            )
        return cls(residue_name=residue,
                   initial_itp=f'{residue}_initial.itp',
                   final_itp=f'{residue}.itp')

    @classmethod
    def ddm_defaults(cls) -> "CGNames":
        return cls(residue_name='DDM', initial_itp='DDM_initial.itp', final_itp='DDM.itp')

    def env(self) -> dict[str, str]:
        return {
            'MOLECULE_TYPE': self.residue_name,
            'INITIAL_ITP': self.initial_itp,
            'FINAL_ITP': self.final_itp,
            'residue_name': self.residue_name,
            'initial_itp': self.initial_itp,
            'final_itp': self.final_itp,
        }


def require_script_compatibility(names: CGNames) -> None:
    """Refuse CG execution if the shipped shell scripts are not migrated."""
    if SHELL_SCRIPTS_READ_ENV:
        return
    if names.residue_name != 'DDM':
        raise ValueError(
            f'CG execution for {names.residue_name!r} is not enabled: the shipped '
            'shell scripts still target DDM. Run '
            'dashboard/execution/scripts/migrate_cg_naming.py --apply first.'
        )
