"""Two--dimensional plane-frame analysis by the direct stiffness method.

The module is deliberately dependency-free.  It is used as the shared
structural engine for box culverts, building beams/columns and continuous
foundations before those tools add code checks and load combinations.

Conventions
-----------
Each node has three global degrees of freedom: ``ux``, ``uy`` and
``rz`` (counter-clockwise positive).  Member local ``x`` runs from node ``i``
to node ``j``; local ``y`` is 90° counter-clockwise from local ``x``.

Member distributed loads may be supplied in global coordinates:

``loads={"wx": 0.0, "wy": -10.0}``

or with linearly varying end intensities:

``loads={"wy_i": -8.0, "wy_j": -12.0}``

Partial uniform loads use ``wy_patch`` with normalized start/end positions:

``loads={"wy_patch": -70.0, "wy_patch_start": 0.3, "wy_patch_end": 0.7}``

The consistent nodal-load vector is integrated with three-point Gauss
quadrature, so linearly varying global loads are handled without approximating
them as an average uniform load.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Iterable, Mapping, Sequence


class FrameAnalysisError(ValueError):
    """Raised for invalid frame data, instability or a singular model."""


RESTRAINT_KEYS = ("ux", "uy", "rz")


def _number(name: str, value: Any, *, minimum: float | None = None) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise FrameAnalysisError(f"{name} must be numeric.") from exc
    if not math.isfinite(v):
        raise FrameAnalysisError(f"{name} must be finite.")
    if minimum is not None and v < minimum:
        raise FrameAnalysisError(f"{name} must be >= {minimum}; got {v}.")
    return v


def _matvec(matrix: Sequence[Sequence[float]], vector: Sequence[float]) -> list[float]:
    return [sum(a * b for a, b in zip(row, vector)) for row in matrix]


def _transpose(matrix: Sequence[Sequence[float]]) -> list[list[float]]:
    return [list(col) for col in zip(*matrix)]


def _matmul(a: Sequence[Sequence[float]], b: Sequence[Sequence[float]]) -> list[list[float]]:
    bt = _transpose(b)
    return [[sum(x * y for x, y in zip(row, col)) for col in bt] for row in a]


def _gauss_solve(matrix: Sequence[Sequence[float]], rhs: Sequence[float]) -> list[float]:
    """Solve a dense linear system with scaled partial pivoting."""

    n = len(rhs)
    if n == 0:
        return []
    if len(matrix) != n or any(len(row) != n for row in matrix):
        raise FrameAnalysisError("Stiffness matrix dimensions are inconsistent.")

    a = [list(map(float, row)) + [float(rhs[i])] for i, row in enumerate(matrix)]
    scales = [max(abs(v) for v in row[:-1]) or 1.0 for row in a]

    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]) / scales[r])
        if abs(a[pivot][col]) < 1e-12 * scales[pivot]:
            raise FrameAnalysisError(
                "Frame stiffness matrix is singular; add adequate supports or restrain "
                "rigid-body translation/rotation."
            )
        if pivot != col:
            a[col], a[pivot] = a[pivot], a[col]
            scales[col], scales[pivot] = scales[pivot], scales[col]

        diag = a[col][col]
        for r in range(col + 1, n):
            factor = a[r][col] / diag
            if factor == 0.0:
                continue
            a[r][col] = 0.0
            for c in range(col + 1, n + 1):
                a[r][c] -= factor * a[col][c]

    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        value = a[r][n] - sum(a[r][c] * x[c] for c in range(r + 1, n))
        x[r] = value / a[r][r]
    return x


@dataclass(frozen=True)
class FrameNode:
    id: str
    x: float
    y: float
    restraint: tuple[bool, bool, bool] = (False, False, False)
    nodal_load: tuple[float, float, float] = (0.0, 0.0, 0.0)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "FrameNode":
        node_id = str(data.get("id", "")).strip()
        if not node_id:
            raise FrameAnalysisError("Every node needs a non-empty id.")

        restraint = data.get("restraint", data.get("restraints", (False, False, False)))
        if isinstance(restraint, Mapping):
            restraint_tuple = tuple(bool(restraint.get(k, False)) for k in RESTRAINT_KEYS)
        elif isinstance(restraint, str):
            keys = {s.strip().lower() for s in restraint.replace(",", " ").split()}
            restraint_tuple = (
                bool(keys & {"ux", "x", "fixed-x"}),
                bool(keys & {"uy", "y", "fixed-y"}),
                bool(keys & {"rz", "r", "rotation", "fixed-r"}),
            )
        else:
            vals = list(restraint)
            if len(vals) != 3:
                raise FrameAnalysisError("Node restraints must contain ux, uy and rz.")
            restraint_tuple = tuple(bool(v) for v in vals)

        return cls(
            id=node_id,
            x=_number(f"node {node_id} x", data.get("x")),
            y=_number(f"node {node_id} y", data.get("y")),
            restraint=restraint_tuple,  # type: ignore[arg-type]
            nodal_load=(
                _number(f"node {node_id} fx", data.get("fx", 0.0)),
                _number(f"node {node_id} fy", data.get("fy", 0.0)),
                _number(f"node {node_id} mz", data.get("mz", 0.0)),
            ),
        )


@dataclass(frozen=True)
class FrameMember:
    id: str
    i: str
    j: str
    E_kn_m2: float
    area_m2: float
    inertia_m4: float
    loads: Mapping[str, float] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "FrameMember":
        member_id = str(data.get("id", "")).strip()
        if not member_id:
            raise FrameAnalysisError("Every member needs a non-empty id.")
        i = str(data.get("i", "")).strip()
        j = str(data.get("j", "")).strip()
        if not i or not j or i == j:
            raise FrameAnalysisError(f"Member {member_id} needs two distinct end nodes.")

        loads = data.get("loads") or {}
        if not isinstance(loads, Mapping):
            raise FrameAnalysisError(f"Member {member_id} loads must be a mapping.")

        return cls(
            id=member_id,
            i=i,
            j=j,
            E_kn_m2=_number(f"member {member_id} E_kn_m2", data.get("E_kn_m2"), minimum=1e-9),
            area_m2=_number(f"member {member_id} area_m2", data.get("area_m2"), minimum=1e-12),
            inertia_m4=_number(
                f"member {member_id} inertia_m4", data.get("inertia_m4"), minimum=1e-12
            ),
            loads={str(k): _number(f"member {member_id} load {k}", v) for k, v in loads.items()},
        )


@dataclass
class MemberResult:
    id: str
    i: str
    j: str
    length_m: float
    local_displacements: tuple[float, ...]
    local_end_forces: tuple[float, ...]
    axial_end_kn: tuple[float, float]
    shear_end_kn: tuple[float, float]
    moment_end_knm: tuple[float, float]
    max_abs_moment_knm: float
    max_moment_position_m: float
    # Sampled internal bending-moment diagram ``(x_m, M_knm)`` from end ``i``.
    # Positive/negative split is needed for face-by-face reinforcement design
    # (top/bottom of a slab, inner/outer face of a wall).
    moment_diagram_knm: list[tuple[float, float]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "i": self.i,
            "j": self.j,
            "length_m": self.length_m,
            "local_displacements": self.local_displacements,
            "local_end_forces": self.local_end_forces,
            "axial_end_kn": self.axial_end_kn,
            "shear_end_kn": self.shear_end_kn,
            "moment_end_knm": self.moment_end_knm,
            "max_abs_moment_knm": self.max_abs_moment_knm,
            "max_moment_position_m": self.max_moment_position_m,
            "moment_diagram_knm": self.moment_diagram_knm,
        }


@dataclass
class FrameResult:
    displacements: dict[str, tuple[float, float, float]]
    reactions: dict[str, tuple[float, float, float]]
    members: dict[str, MemberResult]
    applied_load_vector: tuple[float, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "displacements": self.displacements,
            "reactions": self.reactions,
            "members": {k: v.as_dict() for k, v in self.members.items()},
        }


class FrameModel:
    """A small, deterministic 2D frame model."""

    def __init__(
        self,
        nodes: Iterable[FrameNode | Mapping[str, Any]],
        members: Iterable[FrameMember | Mapping[str, Any]],
    ) -> None:
        self.nodes: list[FrameNode] = [
            n if isinstance(n, FrameNode) else FrameNode.from_mapping(n) for n in nodes
        ]
        self.members: list[FrameMember] = [
            m if isinstance(m, FrameMember) else FrameMember.from_mapping(m) for m in members
        ]
        self._node_index = {n.id: idx for idx, n in enumerate(self.nodes)}
        if len(self._node_index) != len(self.nodes):
            raise FrameAnalysisError("Node ids must be unique.")
        if len(self.nodes) < 2:
            raise FrameAnalysisError("A frame needs at least two nodes.")
        if not self.members:
            raise FrameAnalysisError("A frame needs at least one member.")

        member_ids: set[str] = set()
        for member in self.members:
            if member.id in member_ids:
                raise FrameAnalysisError(f"Duplicate member id: {member.id}")
            member_ids.add(member.id)
            if member.i not in self._node_index or member.j not in self._node_index:
                raise FrameAnalysisError(
                    f"Member {member.id} references an unknown node ({member.i}, {member.j})."
                )
            if self.length(member) <= 1e-12:
                raise FrameAnalysisError(f"Member {member.id} has zero length.")

    @property
    def ndof(self) -> int:
        return 3 * len(self.nodes)

    def _index(self, node_id: str, component: int) -> int:
        return 3 * self._node_index[node_id] + component

    def length(self, member: FrameMember) -> float:
        ni = self.nodes[self._node_index[member.i]]
        nj = self.nodes[self._node_index[member.j]]
        return math.hypot(nj.x - ni.x, nj.y - ni.y)

    def _member_geometry(self, member: FrameMember) -> tuple[float, float, float]:
        ni = self.nodes[self._node_index[member.i]]
        nj = self.nodes[self._node_index[member.j]]
        dx, dy = nj.x - ni.x, nj.y - ni.y
        length = math.hypot(dx, dy)
        return length, dx / length, dy / length

    def _transformation(self, member: FrameMember) -> list[list[float]]:
        _, c, s = self._member_geometry(member)
        return [
            [c, s, 0.0, 0.0, 0.0, 0.0],
            [-s, c, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, c, s, 0.0],
            [0.0, 0.0, 0.0, -s, c, 0.0],
            [0.0, 0.0, 0.0, 0.0, 0.0, 1.0],
        ]

    def local_stiffness(self, member: FrameMember) -> list[list[float]]:
        L = self.length(member)
        ea_l = member.E_kn_m2 * member.area_m2 / L
        ei = member.E_kn_m2 * member.inertia_m4
        a = 12.0 * ei / L**3
        b = 6.0 * ei / L**2
        c = 4.0 * ei / L
        d = 2.0 * ei / L
        return [
            [ea_l, 0.0, 0.0, -ea_l, 0.0, 0.0],
            [0.0, a, b, 0.0, -a, b],
            [0.0, b, c, 0.0, -(6.0 * ei / L**2), d],
            [-ea_l, 0.0, 0.0, ea_l, 0.0, 0.0],
            [0.0, -a, -(6.0 * ei / L**2), 0.0, a, -(6.0 * ei / L**2)],
            [0.0, b, d, 0.0, -(6.0 * ei / L**2), c],
        ]

    def _load_intensity(self, member: FrameMember, xi: float) -> tuple[float, float]:
        loads = member.loads

        def value(base: str) -> tuple[float, float]:
            start = float(loads.get(base + "_i", loads.get(base, 0.0)))
            end = float(loads.get(base + "_j", loads.get(base, start)))
            return start, end

        wx0, wx1 = value("wx")
        wy0, wy1 = value("wy")
        wy = wy0 + (wy1 - wy0) * xi
        if "wy_patch" in loads:
            start = min(1.0, max(0.0, float(loads.get("wy_patch_start", 0.0))))
            end = min(1.0, max(0.0, float(loads.get("wy_patch_end", 1.0))))
            if start > end:
                start, end = end, start
            if start <= xi <= end:
                wy += float(loads["wy_patch"])
        return wx0 + (wx1 - wx0) * xi, wy

    def equivalent_member_load_local(self, member: FrameMember) -> list[float]:
        """Return the consistent nodal-load vector in member-local coordinates."""

        if not member.loads:
            return [0.0] * 6
        L = self.length(member)
        _, c, s = self._member_geometry(member)

        # Three-point Gauss-Legendre integration on xi=[0, 1].  This is exact
        # through degree five, sufficient for linear loads times cubic shapes.
        points = (
            (0.5 - 0.5 * math.sqrt(3.0 / 5.0), 5.0 / 18.0),
            (0.5, 4.0 / 9.0),
            (0.5 + 0.5 * math.sqrt(3.0 / 5.0), 5.0 / 18.0),
        )
        # A partial uniform load is discontinuous.  Split the integration at
        # its two edges so the consistent nodal vector is integrated exactly.
        breaks = [0.0, 1.0]
        if "wy_patch" in member.loads:
            start = min(1.0, max(0.0, float(member.loads.get("wy_patch_start", 0.0))))
            end = min(1.0, max(0.0, float(member.loads.get("wy_patch_end", 1.0))))
            if start > end:
                start, end = end, start
            breaks.extend((start, end))
        breaks = sorted(set(breaks))

        load = [0.0] * 6
        for left, right in zip(breaks, breaks[1:]):
            if right - left <= 1e-12:
                continue
            for point, weight in points:
                xi = left + (right - left) * point
                wx, wy = self._load_intensity(member, xi)
                qx = c * wx + s * wy
                qy = -s * wx + c * wy
                n1 = 1.0 - 3.0 * xi**2 + 2.0 * xi**3
                n2 = L * (xi - 2.0 * xi**2 + xi**3)
                n3 = 3.0 * xi**2 - 2.0 * xi**3
                n4 = L * (-xi**2 + xi**3)
                scale = weight * (right - left) * L
                load[0] += scale * qx * (1.0 - xi)
                load[1] += scale * qy * n1
                load[2] += scale * qy * n2
                load[3] += scale * qx * xi
                load[4] += scale * qy * n3
                load[5] += scale * qy * n4
        return load

    def _global_element(self, member: FrameMember) -> tuple[list[list[float]], list[float], list[float]]:
        T = self._transformation(member)
        k_local = self.local_stiffness(member)
        k_global = _matmul(_matmul(_transpose(T), k_local), T)
        f_local = self.equivalent_member_load_local(member)
        f_global = _matvec(_transpose(T), f_local)
        return k_global, f_local, f_global

    def solve(self) -> FrameResult:
        K = [[0.0] * self.ndof for _ in range(self.ndof)]
        F = [0.0] * self.ndof

        for node in self.nodes:
            base = 3 * self._node_index[node.id]
            for i, value in enumerate(node.nodal_load):
                F[base + i] += value

        element_data: dict[str, tuple[list[list[float]], list[float], list[float]]] = {}
        for member in self.members:
            k_global, f_local, f_global = self._global_element(member)
            element_data[member.id] = (k_global, f_local, f_global)
            dofs = [
                self._index(member.i, 0),
                self._index(member.i, 1),
                self._index(member.i, 2),
                self._index(member.j, 0),
                self._index(member.j, 1),
                self._index(member.j, 2),
            ]
            for a, gi in enumerate(dofs):
                F[gi] += f_global[a]
                for b, gj in enumerate(dofs):
                    K[gi][gj] += k_global[a][b]

        restrained: list[int] = []
        free: list[int] = []
        for node in self.nodes:
            base = 3 * self._node_index[node.id]
            for i, fixed in enumerate(node.restraint):
                (restrained if fixed else free).append(base + i)

        u = [0.0] * self.ndof
        if free:
            Kff = [[K[i][j] for j in free] for i in free]
            Ff = [F[i] for i in free]
            uf = _gauss_solve(Kff, Ff)
            for idx, value in zip(free, uf):
                u[idx] = value

        KU = _matvec(K, u)
        reactions: dict[str, tuple[float, float, float]] = {}
        for node in self.nodes:
            base = 3 * self._node_index[node.id]
            if any(node.restraint):
                reactions[node.id] = tuple(
                    KU[base + i] - F[base + i] if node.restraint[i] else 0.0
                    for i in range(3)
                )
            else:
                reactions[node.id] = (0.0, 0.0, 0.0)

        displacements = {
            node.id: (u[3 * i], u[3 * i + 1], u[3 * i + 2])
            for i, node in enumerate(self.nodes)
        }
        member_results: dict[str, MemberResult] = {}
        for member in self.members:
            T = self._transformation(member)
            k_local = self.local_stiffness(member)
            _, f_local, _ = element_data[member.id]
            d_global = (
                u[self._index(member.i, 0)],
                u[self._index(member.i, 1)],
                u[self._index(member.i, 2)],
                u[self._index(member.j, 0)],
                u[self._index(member.j, 1)],
                u[self._index(member.j, 2)],
            )
            d_local = _matvec(T, d_global)
            q_local = _matvec(k_local, d_local)
            q_local = [a - b for a, b in zip(q_local, f_local)]
            length = self.length(member)

            # Sample the moment diagram from end equilibrium.  This captures the
            # sagging maximum of a uniformly loaded beam as well as end moments.
            max_m = abs(q_local[2])
            max_x = 0.0
            diagram: list[tuple[float, float]] = []
            sample_x = [length * step / 100.0 for step in range(101)]
            if "wy_patch" in member.loads:
                patch_start = min(
                    1.0, max(0.0, float(member.loads.get("wy_patch_start", 0.0)))
                )
                patch_end = min(
                    1.0, max(0.0, float(member.loads.get("wy_patch_end", 1.0)))
                )
                sample_x.extend((patch_start * length, patch_end * length))
                sample_x = sorted(set(round(v, 9) for v in sample_x))
            for x in sample_x:
                # Internal actions at a section measured from end i.  The local
                # end-force vector stores the actions exerted by the member on
                # its nodes; the internal bending moment therefore starts at
                # -q_local[2].
                shear = q_local[1]
                moment = -q_local[2] + shear * x
                # Add the distributed-load contribution using 12-point Simpson.
                if member.loads:
                    cut_points = [0.0, x]
                    if "wy_patch" in member.loads:
                        for value in (patch_start * length, patch_end * length):
                            if 0.0 < value < x:
                                cut_points.append(value)
                    cut_points = sorted(set(round(v, 9) for v in cut_points))
                    _, c, srot = self._member_geometry(member)
                    for xa, xb in zip(cut_points, cut_points[1:]):
                        if xb - xa <= 1e-12:
                            continue
                        shear_load = 0.0
                        moment_load = 0.0
                        nseg = max(2, int(math.ceil(24 * (xb - xa) / length)) * 2)
                        h = (xb - xa) / nseg
                        for s in range(nseg + 1):
                            xp = xa + s * h
                            xi = xp / length
                            wx, wy = self._load_intensity(member, xi)
                            # Transform global load to local transverse intensity.
                            qy = -srot * wx + c * wy
                            w = 1.0 if s in (0, nseg) else (4.0 if s % 2 else 2.0)
                            shear_load += w * qy
                            moment_load += w * qy * (x - xp)
                        shear += shear_load * h / 3.0
                        moment += moment_load * h / 3.0
                if abs(moment) > max_m:
                    max_m = abs(moment)
                    max_x = x
                diagram.append((round(x, 6), round(moment, 6)))

            member_results[member.id] = MemberResult(
                id=member.id,
                i=member.i,
                j=member.j,
                length_m=length,
                local_displacements=tuple(d_local),
                local_end_forces=tuple(q_local),
                axial_end_kn=(-q_local[0], q_local[3]),
                shear_end_kn=(q_local[1], -q_local[4]),
                moment_end_knm=(-q_local[2], q_local[5]),
                max_abs_moment_knm=max_m,
                max_moment_position_m=max_x,
                moment_diagram_knm=diagram,
            )

        return FrameResult(
            displacements=displacements,
            reactions=reactions,
            members=member_results,
            applied_load_vector=tuple(F),
        )


def analyse(
    nodes: Iterable[FrameNode | Mapping[str, Any]],
    members: Iterable[FrameMember | Mapping[str, Any]],
) -> FrameResult:
    """Convenience wrapper for :class:`FrameModel`."""

    return FrameModel(nodes, members).solve()

