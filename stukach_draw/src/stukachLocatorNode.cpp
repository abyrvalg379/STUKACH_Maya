#include "stukachLocatorNode.h"

#include <maya/MFnNumericAttribute.h>
#include <maya/MFnTypedAttribute.h>
#include <maya/MFnEnumAttribute.h>
#include <maya/MFnMessageAttribute.h>
#include <maya/MFnDagNode.h>
#include <maya/MPlug.h>
#include <maya/MPlugArray.h>
#include <maya/MDataBlock.h>
#include <maya/MDataHandle.h>
#include <maya/MGlobal.h>
#include <maya/MPoint.h>
#include <maya/MMatrix.h>
#include <maya/MDagPath.h>

// ── Static members ───────────────────────────────────────────────────────────

MTypeId StukachLocatorNode::id(0x0013a7b0);  // unique node ID
MString StukachLocatorNode::typeName             = "stukachLocator";
MString StukachLocatorNode::drawDbClassification = "drawdb/geometry/stukachDrawOverrider";
MString StukachLocatorNode::drawRegistrantId     = "stukachDrawOverrider";

MObject StukachLocatorNode::aInputMesh;
MObject StukachLocatorNode::aBadFaces;
MObject StukachLocatorNode::aBadEdges;
MObject StukachLocatorNode::aBadVerts;
MObject StukachLocatorNode::aFaceColorR;
MObject StukachLocatorNode::aFaceColorG;
MObject StukachLocatorNode::aFaceColorB;
MObject StukachLocatorNode::aFaceColor;
MObject StukachLocatorNode::aEdgeColorR;
MObject StukachLocatorNode::aEdgeColorG;
MObject StukachLocatorNode::aEdgeColorB;
MObject StukachLocatorNode::aEdgeColor;
MObject StukachLocatorNode::aPointColorR;
MObject StukachLocatorNode::aPointColorG;
MObject StukachLocatorNode::aPointColorB;
MObject StukachLocatorNode::aPointColor;
MObject StukachLocatorNode::aDrawEnabled;
MObject StukachLocatorNode::aDrawMode;
MObject StukachLocatorNode::aBBoxMinX;
MObject StukachLocatorNode::aBBoxMinY;
MObject StukachLocatorNode::aBBoxMinZ;
MObject StukachLocatorNode::aBBoxMin;
MObject StukachLocatorNode::aBBoxMaxX;
MObject StukachLocatorNode::aBBoxMaxY;
MObject StukachLocatorNode::aBBoxMaxZ;
MObject StukachLocatorNode::aBBoxMax;
MObject StukachLocatorNode::aDrawBBox;

// ── Creator ─────────────────────────────────────────────────────────────────

void* StukachLocatorNode::creator()
{
    return new StukachLocatorNode();
}

// ── Bounding box — VP2 frustum culling ──────────────────────────────────────
// The overlay draws world-space geometry; with an empty default box (at the
// origin) VP2 culls the drawable whenever the camera looks elsewhere. Return
// the actual overlay extent so it is never wrongly culled.

MBoundingBox StukachLocatorNode::boundingBox() const
{
    // EMPTY on purpose. Maya uses the NODE bounding box for viewport
    // SELECTION picking as well as culling: returning the connected mesh's
    // bbox made the invisible locator span the whole object, so clicking
    // the mesh selected the locator instead (selection "flicker").
    // Frustum culling is handled by StukachDrawOverride::boundingBox,
    // which still reports the real overlay extent.
    return MBoundingBox();
}

// ── Initialize — declare all attributes ─────────────────────────────────────

MStatus StukachLocatorNode::initialize()
{
    MStatus status;
    MFnNumericAttribute nAttr;
    MFnTypedAttribute tAttr;
    MFnEnumAttribute eAttr;
    MFnMessageAttribute mAttr;

    // Input mesh (message connection)
    aInputMesh = mAttr.create("inputMesh", "inMesh", &status);
    CHECK_MSTATUS_AND_RETURN_IT(status);
    status = addAttribute(aInputMesh);
    CHECK_MSTATUS_AND_RETURN_IT(status);

    // Bad component strings — "0,5,12,..."
    aBadFaces = tAttr.create("badFaces", "bf", MFnData::kString, &status);
    CHECK_MSTATUS_AND_RETURN_IT(status);
    tAttr.setStorable(true);
    tAttr.setWritable(true);
    tAttr.setReadable(true);
    status = addAttribute(aBadFaces);
    CHECK_MSTATUS_AND_RETURN_IT(status);

    aBadEdges = tAttr.create("badEdges", "be", MFnData::kString, &status);
    CHECK_MSTATUS_AND_RETURN_IT(status);
    tAttr.setStorable(true);
    tAttr.setWritable(true);
    tAttr.setReadable(true);
    status = addAttribute(aBadEdges);
    CHECK_MSTATUS_AND_RETURN_IT(status);

    aBadVerts = tAttr.create("badVerts", "bv", MFnData::kString, &status);
    CHECK_MSTATUS_AND_RETURN_IT(status);
    tAttr.setStorable(true);
    tAttr.setWritable(true);
    tAttr.setReadable(true);
    status = addAttribute(aBadVerts);
    CHECK_MSTATUS_AND_RETURN_IT(status);

    // Face color (float3)
    aFaceColorR = nAttr.create("faceColorR", "fcr", MFnNumericData::kFloat, 1.0f, &status);
    CHECK_MSTATUS_AND_RETURN_IT(status);
    aFaceColorG = nAttr.create("faceColorG", "fcg", MFnNumericData::kFloat, 0.15f, &status);
    CHECK_MSTATUS_AND_RETURN_IT(status);
    aFaceColorB = nAttr.create("faceColorB", "fcb", MFnNumericData::kFloat, 0.15f, &status);
    CHECK_MSTATUS_AND_RETURN_IT(status);
    aFaceColor = nAttr.create("faceColor", "fc", aFaceColorR, aFaceColorG, aFaceColorB, &status);
    CHECK_MSTATUS_AND_RETURN_IT(status);
    nAttr.setStorable(true);
    nAttr.setWritable(true);
    nAttr.setKeyable(true);
    status = addAttribute(aFaceColor);
    CHECK_MSTATUS_AND_RETURN_IT(status);

    // Edge color (float3)
    aEdgeColorR = nAttr.create("edgeColorR", "ecr", MFnNumericData::kFloat, 0.0f, &status);
    CHECK_MSTATUS_AND_RETURN_IT(status);
    aEdgeColorG = nAttr.create("edgeColorG", "ecg", MFnNumericData::kFloat, 0.0f, &status);
    CHECK_MSTATUS_AND_RETURN_IT(status);
    aEdgeColorB = nAttr.create("edgeColorB", "ecb", MFnNumericData::kFloat, 0.4f, &status);
    CHECK_MSTATUS_AND_RETURN_IT(status);
    aEdgeColor = nAttr.create("edgeColor", "ec", aEdgeColorR, aEdgeColorG, aEdgeColorB, &status);
    CHECK_MSTATUS_AND_RETURN_IT(status);
    nAttr.setStorable(true);
    nAttr.setWritable(true);
    nAttr.setKeyable(true);
    status = addAttribute(aEdgeColor);
    CHECK_MSTATUS_AND_RETURN_IT(status);

    // Point color (float3)
    aPointColorR = nAttr.create("pointColorR", "pcr", MFnNumericData::kFloat, 1.0f, &status);
    CHECK_MSTATUS_AND_RETURN_IT(status);
    aPointColorG = nAttr.create("pointColorG", "pcg", MFnNumericData::kFloat, 1.0f, &status);
    CHECK_MSTATUS_AND_RETURN_IT(status);
    aPointColorB = nAttr.create("pointColorB", "pcb", MFnNumericData::kFloat, 0.0f, &status);
    CHECK_MSTATUS_AND_RETURN_IT(status);
    aPointColor = nAttr.create("pointColor", "pc", aPointColorR, aPointColorG, aPointColorB, &status);
    CHECK_MSTATUS_AND_RETURN_IT(status);
    nAttr.setStorable(true);
    nAttr.setWritable(true);
    nAttr.setKeyable(true);
    status = addAttribute(aPointColor);
    CHECK_MSTATUS_AND_RETURN_IT(status);

    // Draw enabled (bool)
    aDrawEnabled = nAttr.create("drawEnabled", "den", MFnNumericData::kBoolean, 1, &status);
    CHECK_MSTATUS_AND_RETURN_IT(status);
    nAttr.setStorable(true);
    nAttr.setWritable(true);
    nAttr.setKeyable(true);
    status = addAttribute(aDrawEnabled);
    CHECK_MSTATUS_AND_RETURN_IT(status);

    // Draw mode (enum)
    aDrawMode = eAttr.create("drawMode", "dm", 0, &status);
    CHECK_MSTATUS_AND_RETURN_IT(status);
    eAttr.addField("overview", 0);
    eAttr.addField("single_check", 1);
    eAttr.setStorable(true);
    eAttr.setWritable(true);
    status = addAttribute(aDrawMode);
    CHECK_MSTATUS_AND_RETURN_IT(status);

    // Bounding-box min (float3) — for transform-level issues
    aBBoxMinX = nAttr.create("bboxMinX", "bnx", MFnNumericData::kFloat, 0.0f, &status);
    CHECK_MSTATUS_AND_RETURN_IT(status);
    aBBoxMinY = nAttr.create("bboxMinY", "bny", MFnNumericData::kFloat, 0.0f, &status);
    CHECK_MSTATUS_AND_RETURN_IT(status);
    aBBoxMinZ = nAttr.create("bboxMinZ", "bnz", MFnNumericData::kFloat, 0.0f, &status);
    CHECK_MSTATUS_AND_RETURN_IT(status);
    aBBoxMin = nAttr.create("bboxMin", "bn", aBBoxMinX, aBBoxMinY, aBBoxMinZ, &status);
    CHECK_MSTATUS_AND_RETURN_IT(status);
    nAttr.setStorable(true);
    nAttr.setWritable(true);
    status = addAttribute(aBBoxMin);
    CHECK_MSTATUS_AND_RETURN_IT(status);

    // Bounding-box max (float3)
    aBBoxMaxX = nAttr.create("bboxMaxX", "bxx", MFnNumericData::kFloat, 0.0f, &status);
    CHECK_MSTATUS_AND_RETURN_IT(status);
    aBBoxMaxY = nAttr.create("bboxMaxY", "bxy", MFnNumericData::kFloat, 0.0f, &status);
    CHECK_MSTATUS_AND_RETURN_IT(status);
    aBBoxMaxZ = nAttr.create("bboxMaxZ", "bxz", MFnNumericData::kFloat, 0.0f, &status);
    CHECK_MSTATUS_AND_RETURN_IT(status);
    aBBoxMax = nAttr.create("bboxMax", "bx", aBBoxMaxX, aBBoxMaxY, aBBoxMaxZ, &status);
    CHECK_MSTATUS_AND_RETURN_IT(status);
    nAttr.setStorable(true);
    nAttr.setWritable(true);
    status = addAttribute(aBBoxMax);
    CHECK_MSTATUS_AND_RETURN_IT(status);

    // Draw bounding box (bool) — wireframe cube for transform issues
    aDrawBBox = nAttr.create("drawBBox", "dbb", MFnNumericData::kBoolean, 0, &status);
    CHECK_MSTATUS_AND_RETURN_IT(status);
    nAttr.setStorable(true);
    nAttr.setWritable(true);
    status = addAttribute(aDrawBBox);
    CHECK_MSTATUS_AND_RETURN_IT(status);

    // Attribute dependencies — changing any of these triggers redraw
    attributeAffects(aBadFaces, aBadFaces);
    attributeAffects(aBadEdges, aBadEdges);
    attributeAffects(aBadVerts, aBadVerts);
    attributeAffects(aDrawEnabled, aBadFaces);
    attributeAffects(aDrawMode, aBadFaces);
    attributeAffects(aFaceColor, aBadFaces);
    attributeAffects(aEdgeColor, aBadFaces);
    attributeAffects(aPointColor, aBadFaces);
    attributeAffects(aBBoxMin, aBadFaces);
    attributeAffects(aBBoxMax, aBadFaces);
    attributeAffects(aDrawBBox, aBadFaces);

    return MS::kSuccess;
}

// ── Post-constructor ────────────────────────────────────────────────────────

void StukachLocatorNode::postConstructor()
{
    // Nothing needed — draw override handles all rendering
}

// ── Compute ─────────────────────────────────────────────────────────────────

MStatus StukachLocatorNode::compute(const MPlug& plug, MDataBlock& data)
{
    // This node doesn't have complex compute — the draw override reads
    // attributes directly. Just mark clean.
    return MS::kSuccess;
}
