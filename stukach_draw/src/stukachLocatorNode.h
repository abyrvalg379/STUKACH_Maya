#ifndef STUKACH_LOCATOR_NODE_H
#define STUKACH_LOCATOR_NODE_H

#include <maya/MPxLocatorNode.h>
#include <maya/MBoundingBox.h>
#include <maya/MObject.h>
#include <maya/MString.h>
#include <maya/MTypeId.h>

class StukachLocatorNode : public MPxLocatorNode
{
public:
    StukachLocatorNode() = default;
    ~StukachLocatorNode() override = default;

    static void* creator();
    static MStatus initialize();

    void postConstructor() override;
    MStatus compute(const MPlug& plug, MDataBlock& data) override;

    // VP2 frustum-culls the drawable by this box. The default (empty) box sits
    // at the origin, so overlays of meshes far from the origin get culled —
    // cover the actual overlay extent instead.
    MBoundingBox boundingBox() const override;

    // Draw classification — links this node to its draw override
    static MString typeName;
    static MString drawDbClassification;
    static MString drawRegistrantId;

    // ── Attributes ────────────────────────────────────────────────────────

    // Input: mesh to read topology from (message connection to mesh shape)
    static MObject aInputMesh;

    // Bad component data — serialized as "0,5,12,..." strings
    static MObject aBadFaces;     // face indices
    static MObject aBadEdges;     // edge indices
    static MObject aBadVerts;     // vertex indices

    // Colors (float3)
    static MObject aFaceColorR;
    static MObject aFaceColorG;
    static MObject aFaceColorB;
    static MObject aFaceColor;

    static MObject aEdgeColorR;
    static MObject aEdgeColorG;
    static MObject aEdgeColorB;
    static MObject aEdgeColor;

    static MObject aPointColorR;
    static MObject aPointColorG;
    static MObject aPointColorB;
    static MObject aPointColor;

    // Controls
    static MObject aDrawEnabled;  // bool — master on/off
    static MObject aDrawMode;     // enum: 0=overview, 1=single-check

    // Bounding-box overlay (transform-level issues: rotation/scale/pivot)
    static MObject aBBoxMinX;
    static MObject aBBoxMinY;
    static MObject aBBoxMinZ;
    static MObject aBBoxMin;
    static MObject aBBoxMaxX;
    static MObject aBBoxMaxY;
    static MObject aBBoxMaxZ;
    static MObject aBBoxMax;
    static MObject aDrawBBox;     // bool — draw wireframe cube instead of faces

    // Node ID (unique — pick a random one)
    static MTypeId id;
};

#endif // STUKACH_LOCATOR_NODE_H
