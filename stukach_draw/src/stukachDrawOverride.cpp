#include "stukachDrawOverride.h"
#include "stukachLocatorNode.h"
#include "stukachData.h"

#include <maya/MFnDependencyNode.h>
#include <maya/MFnDagNode.h>
#include <maya/MFnMesh.h>
#include <maya/MItMeshPolygon.h>
#include <maya/MItMeshVertex.h>
#include <maya/MItMeshEdge.h>
#include <maya/MDagPath.h>
#include <maya/MSelectionList.h>
#include <maya/MPlug.h>
#include <maya/MString.h>
#include <maya/MEventMessage.h>
#include <maya/MCallbackIdArray.h>
#include <maya/MObjectHandle.h>
#include <maya/MViewport2Renderer.h>
#include <maya/MUIDrawManager.h>
#include <maya/MPointArray.h>
#include <maya/MColor.h>

#include <sstream>
#include <string>

using namespace MHWRender;

// ── Creator ─────────────────────────────────────────────────────────────────

MPxDrawOverride* StukachDrawOverride::creator(const MObject& obj)
{
    return new StukachDrawOverride(obj);
}

// ── Constructor ─────────────────────────────────────────────────────────────

StukachDrawOverride::StukachDrawOverride(const MObject& obj)
    : MPxDrawOverride(obj, NULL, false)  // isAlwaysDirty = false — performance over live updates
    , fNode(obj)
{
    // Register callback to mark dirty when viewport display mode changes
    fModelEditorChangedCb = MEventMessage::addEventCallback(
        "modelEditorChanged",
        [](void* clientData) {
            MObject* node = static_cast<MObject*>(clientData);
            if (node) {
                // Guard: the event can fire while the owning override is
                // already destroyed (dangling clientData) or the node is
                // being deleted by scene teardown (File > New) — calling
                // setGeometryDrawDirty with a dead MObject crashed Maya
                // (ACCESS_VIOLATION in TdrawDbSync::geometryChanged).
                MObjectHandle handle(*node);
                if (handle.isAlive() && !node->isNull()) {
                    MRenderer::setGeometryDrawDirty(*node);
                }
            }
        },
        &fNode
    );
}

// ── Destructor ──────────────────────────────────────────────────────────────

StukachDrawOverride::~StukachDrawOverride()
{
    // The callback receives &fNode (a member of THIS instance). Without
    // removal it fires with a dangling pointer after the override dies.
    if (fModelEditorChangedCb) {
        MEventMessage::removeCallback(fModelEditorChangedCb);
        fModelEditorChangedCb = 0;
    }
}

// ── Supported draw APIs ─────────────────────────────────────────────────────

DrawAPI StukachDrawOverride::supportedDrawAPIs() const
{
    return kAllDevices;
}

// ── Bounding box for VP2 frustum culling ─────────────────────────────────────

MBoundingBox StukachDrawOverride::boundingBox(
    const MDagPath& objPath,
    const MDagPath& cameraPath) const
{
    MStatus status;
    MFnDependencyNode depNode(objPath.node(), &status);
    if (!status) return MBoundingBox();

    // Transform-issue wireframe: extent comes straight from the bbox attrs
    MPlug dbbPlug = depNode.findPlug(StukachLocatorNode::aDrawBBox, false, &status);
    if (status && dbbPlug.asBool()) {
        MPlug mn = depNode.findPlug(StukachLocatorNode::aBBoxMin, false);
        MPlug mx = depNode.findPlug(StukachLocatorNode::aBBoxMax, false);
        if (!mn.isNull() && !mx.isNull()) {
            MPoint a(mn.child(0).asFloat(), mn.child(1).asFloat(), mn.child(2).asFloat());
            MPoint b(mx.child(0).asFloat(), mx.child(1).asFloat(), mx.child(2).asFloat());
            return MBoundingBox(a, b);
        }
    }

    // Component overlay: cover the connected mesh, transformed to world space
    MDagPath meshPath;
    if (!getConnectedMesh(objPath, meshPath)) return MBoundingBox();
    MFnDagNode dagFn(meshPath, &status);
    if (!status) return MBoundingBox();
    MBoundingBox bb = dagFn.boundingBox();
    bb.transformUsing(meshPath.inclusiveMatrix());
    return bb;
}

// ── Helper: parse "0,5,12,..." string into int array ────────────────────────

void StukachDrawOverride::parseIndexString(const MString& str, MIntArray& indices)
{
    indices.clear();
    if (str.length() == 0) return;

    std::string s(str.asChar());
    std::istringstream iss(s);
    std::string token;
    while (std::getline(iss, token, ',')) {
        if (!token.empty()) {
            indices.append(std::stoi(token));
        }
    }
}

// ── Helper: get connected mesh dag path ─────────────────────────────────────

bool StukachDrawOverride::getConnectedMesh(
    const MDagPath& locatorPath,
    MDagPath& meshPath)
{
    MStatus status;
    MFnDependencyNode depNode(locatorPath.node(), &status);
    if (!status) return false;

    MPlug inMeshPlug = depNode.findPlug(StukachLocatorNode::aInputMesh, false, &status);
    if (!status || inMeshPlug.isNull()) return false;

    // Follow the connection to the mesh shape
    MPlugArray sources;
    inMeshPlug.connectedTo(sources, true, false);
    if (sources.length() == 0) return false;

    MObject meshObj = sources[0].node();
    if (meshObj.isNull() || !meshObj.hasFn(MFn::kMesh)) return false;

    // MFnDagNode::getPath is thread-safe from prepareForDraw worker threads,
    // unlike MSelectionList::add(MObject) which yields an invalid DAG path there.
    MStatus dagStatus;
    MFnDagNode dagFn(meshObj, &dagStatus);
    if (!dagStatus) return false;
    MDagPath dag;
    dagStatus = dagFn.getPath(dag);
    if (!dagStatus || !dag.isValid()) return false;

    // Verify mesh has valid geometry
    MStatus meshStatus;
    MFnMesh testMesh(dag, &meshStatus);
    if (!meshStatus || testMesh.numPolygons() == 0) return false;

    meshPath = dag;
    return true;
}

// ── Helper: build triangle verts from face indices ──────────────────────────

// Maximum bad faces to draw per object — prevents VP2 memory exhaustion
// on production assets. Lower limit for isAlwaysDirty=true performance.
#define STUKACH_MAX_DRAW_FACES 2000

void StukachDrawOverride::buildFaceTriangles(
    const MDagPath& meshPath,
    const MIntArray& faceIds,
    MPointArray& outVerts,
    MPointArray& outEdges,
    float normalOffset)
{
    outVerts.clear();
    outEdges.clear();

    MStatus status;
    MFnMesh meshFn(meshPath, &status);
    if (!status) return;

    // Cap: don't build geometry for more than STUKACH_MAX_DRAW_FACES faces
    unsigned nFacesToDraw = faceIds.length();
    if (nFacesToDraw > STUKACH_MAX_DRAW_FACES) {
        nFacesToDraw = STUKACH_MAX_DRAW_FACES;
    }

    // Read all vertex positions ONCE (not per-face — very expensive)
    MPointArray allPts;
    meshFn.getPoints(allPts, MSpace::kWorld);
    unsigned nPts = allPts.length();
    if (nPts == 0) return;

    for (unsigned i = 0; i < nFacesToDraw; i++) {
        int fi = faceIds[i];
        if (fi < 0 || fi >= (int)meshFn.numPolygons()) continue;

        // Get face normal for offset
        MVector normal;
        meshFn.getPolygonNormal(fi, normal, MSpace::kWorld);

        // Get face vertex indices
        MIntArray vertIndices;
        meshFn.getPolygonVertices(fi, vertIndices);
        if (vertIndices.length() < 3) continue;

        // Bounds check: skip face if any vertex index is out of range
        bool valid = true;
        MPointArray facePts(vertIndices.length());
        for (unsigned j = 0; j < vertIndices.length(); j++) {
            int vi = vertIndices[j];
            if (vi < 0 || (unsigned)vi >= nPts) { valid = false; break; }
            facePts[j] = allPts[vi];
        }
        if (!valid) continue;

        // Offset vertices along normal to avoid z-fighting
        MPointArray offsetPts(facePts.length());
        for (unsigned j = 0; j < facePts.length(); j++) {
            offsetPts[j] = facePts[j] + normal * normalOffset;
        }

        // Fan triangulation for filled triangles
        for (unsigned j = 1; j + 1 < offsetPts.length(); j++) {
            outVerts.append(offsetPts[0]);
            outVerts.append(offsetPts[j]);
            outVerts.append(offsetPts[j + 1]);
        }

        // Edges (wireframe)
        for (unsigned j = 0; j < offsetPts.length(); j++) {
            outEdges.append(offsetPts[j]);
            outEdges.append(offsetPts[(j + 1) % offsetPts.length()]);
        }
    }
}

// ── Helper: build point array from vertex indices ───────────────────────────

void StukachDrawOverride::buildVertPoints(
    const MDagPath& meshPath,
    const MIntArray& vertIds,
    MPointArray& outPoints)
{
    outPoints.clear();

    MStatus status;
    MFnMesh meshFn(meshPath, &status);
    if (!status) return;

    MPointArray allPts;
    meshFn.getPoints(allPts, MSpace::kWorld);

    for (unsigned i = 0; i < vertIds.length(); i++) {
        int vi = vertIds[i];
        if (vi >= 0 && vi < (int)allPts.length()) {
            outPoints.append(allPts[vi]);
        }
    }
}

// ── prepareForDraw — read data from node, build geometry ────────────────────

MUserData* StukachDrawOverride::prepareForDraw(
    const MDagPath& objPath,
    const MDagPath& cameraPath,
    const MFrameContext& frameContext,
    MUserData* oldData)
{
    StukachData* data = dynamic_cast<StukachData*>(oldData);
    if (!data) {
        data = new StukachData();
    }

    MStatus status;
    MFnDependencyNode depNode(objPath.node(), &status);
    if (!status) {
        data->dirty = false;
        return data;
    }

    // Read draw enabled
    MPlug enabledPlug = depNode.findPlug(StukachLocatorNode::aDrawEnabled, false, &status);
    if (!status || !enabledPlug.asBool()) {
        data->dirty = false;
        data->faceVerts.clear();
        data->faceEdges.clear();
        data->badPoints.clear();
        data->drawBBox = false;
        data->bboxEdges.clear();
        return data;
    }

    // Read draw mode
    MPlug modePlug = depNode.findPlug(StukachLocatorNode::aDrawMode, false, &status);
    data->drawMode = status ? modePlug.asInt() : 0;

    // Read colors
    MPlug faceColorPlug = depNode.findPlug(StukachLocatorNode::aFaceColor, false, &status);
    if (status) {
        data->faceColor = MColor(
            faceColorPlug.child(0).asFloat(),
            faceColorPlug.child(1).asFloat(),
            faceColorPlug.child(2).asFloat()
        );
    } else {
        data->faceColor = MColor(1.0f, 0.15f, 0.15f);
    }

    MPlug edgeColorPlug = depNode.findPlug(StukachLocatorNode::aEdgeColor, false, &status);
    if (status) {
        data->edgeColor = MColor(
            edgeColorPlug.child(0).asFloat(),
            edgeColorPlug.child(1).asFloat(),
            edgeColorPlug.child(2).asFloat()
        );
    } else {
        data->edgeColor = MColor(0.0f, 0.015f, 0.4f);
    }

    MPlug pointColorPlug = depNode.findPlug(StukachLocatorNode::aPointColor, false, &status);
    if (status) {
        data->pointColor = MColor(
            pointColorPlug.child(0).asFloat(),
            pointColorPlug.child(1).asFloat(),
            pointColorPlug.child(2).asFloat()
        );
    } else {
        data->pointColor = MColor(1.0f, 1.0f, 0.0f);
    }

    // Read bounding-box overlay state (transform-level issues)
    MPlug drawBBoxPlug = depNode.findPlug(StukachLocatorNode::aDrawBBox, false, &status);
    data->drawBBox = (status && drawBBoxPlug.asBool());
    data->bboxEdges.clear();

    if (data->drawBBox) {
        MPlug bboxMinPlug = depNode.findPlug(StukachLocatorNode::aBBoxMin, false, &status);
        MPlug bboxMaxPlug = depNode.findPlug(StukachLocatorNode::aBBoxMax, false, &status);
        if (status && !bboxMinPlug.isNull() && !bboxMaxPlug.isNull()) {
            float mnx = bboxMinPlug.child(0).asFloat();
            float mny = bboxMinPlug.child(1).asFloat();
            float mnz = bboxMinPlug.child(2).asFloat();
            float mxx = bboxMaxPlug.child(0).asFloat();
            float mxy = bboxMaxPlug.child(1).asFloat();
            float mxz = bboxMaxPlug.child(2).asFloat();
            // 8 corners
            MPoint c[8] = {
                MPoint(mnx, mny, mnz), MPoint(mxx, mny, mnz),
                MPoint(mxx, mny, mxz), MPoint(mnx, mny, mxz),
                MPoint(mnx, mxy, mnz), MPoint(mxx, mxy, mnz),
                MPoint(mxx, mxy, mxz), MPoint(mnx, mxy, mxz)
            };
            // 12 edges as line pairs
            int edges[12][2] = {
                {0,1},{1,2},{2,3},{3,0},   // bottom
                {4,5},{5,6},{6,7},{7,4},   // top
                {0,4},{1,5},{2,6},{3,7}    // verticals
            };
            for (int i = 0; i < 12; i++) {
                data->bboxEdges.append(c[edges[i][0]]);
                data->bboxEdges.append(c[edges[i][1]]);
            }
        } else {
            data->drawBBox = false;
        }
    }

    // Get connected mesh
    MDagPath meshPath;
    bool hasMesh = getConnectedMesh(objPath, meshPath);

    // Read bad component strings
    MString badFacesStr, badEdgesStr, badVertsStr;

    MPlug facesPlug = depNode.findPlug(StukachLocatorNode::aBadFaces, false, &status);
    if (status) badFacesStr = facesPlug.asString();

    MPlug edgesPlug = depNode.findPlug(StukachLocatorNode::aBadEdges, false, &status);
    if (status) badEdgesStr = edgesPlug.asString();

    MPlug vertsPlug = depNode.findPlug(StukachLocatorNode::aBadVerts, false, &status);
    if (status) badVertsStr = vertsPlug.asString();

    // Parse indices
    MIntArray faceIds, edgeIds, vertIds;
    parseIndexString(badFacesStr, faceIds);
    parseIndexString(badEdgesStr, edgeIds);
    parseIndexString(badVertsStr, vertIds);

    // Build geometry if mesh is connected
    data->faceVerts.clear();
    data->faceEdges.clear();
    data->badPoints.clear();

    if (hasMesh) {
        try {
            if (faceIds.length() > 0) {
                buildFaceTriangles(meshPath, faceIds, data->faceVerts, data->faceEdges, 0.001f);
            }
            if (vertIds.length() > 0) {
                buildVertPoints(meshPath, vertIds, data->badPoints);
            }
        } catch (...) {
            // Swallow exceptions to prevent Maya crash
            data->faceVerts.clear();
            data->faceEdges.clear();
            data->badPoints.clear();
        }
    }

    data->dirty = true;
    return data;
}

// ── addUIDrawables — draw in viewport ───────────────────────────────────────

void StukachDrawOverride::addUIDrawables(
    const MDagPath& objPath,
    MUIDrawManager& drawManager,
    const MFrameContext& frameContext,
    const MUserData* data)
{
    const StukachData* stukachData = dynamic_cast<const StukachData*>(data);
    if (!stukachData || !stukachData->dirty) return;

    // Nothing to draw
    if (stukachData->faceVerts.length() == 0 &&
        stukachData->faceEdges.length() == 0 &&
        stukachData->badPoints.length() == 0 &&
        stukachData->bboxEdges.length() == 0) return;

    drawManager.beginDrawable(MUIDrawManager::kNonSelectable);
    drawManager.setLineStyle(MUIDrawManager::kSolid);

    // Draw filled bad faces (red)
    if (stukachData->faceVerts.length() > 0) {
        drawManager.setColor(stukachData->faceColor);
        drawManager.mesh(MUIDrawManager::kTriangles, stukachData->faceVerts);
    }

    // Draw wireframe edges of bad faces (dark blue)
    if (stukachData->faceEdges.length() > 0) {
        drawManager.setColor(stukachData->edgeColor);
        drawManager.mesh(MUIDrawManager::kLines, stukachData->faceEdges);
    }

    // Draw bad vertices (yellow points)
    if (stukachData->badPoints.length() > 0) {
        drawManager.setColor(stukachData->pointColor);
        drawManager.setPointSize(4.0f);
        drawManager.mesh(MUIDrawManager::kPoints, stukachData->badPoints);
    }

    // Draw bounding-box wireframe (transform issues) in face color, thick lines
    if (stukachData->bboxEdges.length() > 0) {
        drawManager.setColor(stukachData->faceColor);
        drawManager.setLineWidth(2.5f);
        drawManager.mesh(MUIDrawManager::kLines, stukachData->bboxEdges);
    }

    drawManager.endDrawable();
}
