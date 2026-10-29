"""The house surface conventions: element radii and the probe both features' shape analyses assume.

These were `surfaces.py`'s own constants, and the protein-detergent encapsulation estimate imported them from there.
Once the two analyses belong to different distributions, the shared convention needs a home in the engine -- a copy in
each feature would be a second convention, and the two would drift.
"""

#: Van der Waals radii, nm, by element.
AA_RADII = {'H':.109,'C':.175,'N':.161,'O':.156,'F':.144,'P':.180,'S':.179,'Cl':.174,'Br':.185,'I':.200}

#: The probe radius every surface calculation here uses, nm.
PROBE = .191
