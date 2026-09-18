#ifndef STUKACH_DATA_H
#define STUKACH_DATA_H

#include <maya/MUserData.h>
#include <maya/MPointArray.h>
#include <maya/MColor.h>

// Per-shape draw data — carried from prepareForDraw() to addUIDrawables().
class StukachData : public MUserData
{
public:
#if MAYA_API_VERSION < 20220000
    StukachData() : MUserData(false) {}
#else
    StukachData() : MUserData() {}
#endif

    // Filled triangles (bad faces)
    MPointArray faceVerts;
    MPointArray faceEdges;   // wireframe edges of bad faces
    MPointArray badPoints;   // bad vertices

    // Colors (set from node attributes)
    MColor faceColor;
    MColor edgeColor;
    MColor pointColor;

    // Draw mode: 0 = overview (red/yellow layers), 1 = single-check (per-face)
    int drawMode = 0;

    // Bounding-box wireframe (transform-level issues: rotation/scale/pivot).
    // When drawBBox is true the 12 edges of bboxMin..bboxMax are in bboxEdges.
    bool drawBBox = false;
    MPointArray bboxEdges;

    // Dirty flag — if false, old data can be reused
    bool dirty = true;
};

#endif // STUKACH_DATA_H
