# Sigma.js 3 (WebGL) with graphology for graph rendering, pinned below Sigma 4

The MDKG map renders with Sigma.js through `@react-sigma/core` 5, laid out with graphology's ForceAtlas2. It is WebGL-based, so it stays fluid beyond a few thousand nodes, where SVG/canvas force graphs struggle. Sigma 4 (with react-sigma 6) was tried first, but it is a ground-up rewrite: node/edge reducers and label-colour settings are replaced by a new primitives/styles system. We pinned the mature 3.x line rather than build on that newer API. Revisit when react-sigma's Sigma 4 support and documentation settle.
