#ifndef STUKACH_DRAW_OVERRIDE_H
#define STUKACH_DRAW_OVERRIDE_H

#include <maya/MPxDrawOverride.h>
#include <maya/MBoundingBox.h>
#include <maya/MObject.h>
#include <maya/MString.h>
#include <maya/MViewport2Renderer.h>
#include <maya/MCallbackIdArray.h>

class StukachDrawOverride : public MHWRender::MPxDrawOverride
{
public:
    static MHWRender::MPxDrawOverride* creator(const MObject& obj);

    MHWRender::DrawAPI supportedDrawAPIs() const override;
    bool hasUIDrawables() const override { return true; }

    // VP2 frustum-culls the drawable by THIS box (not the node's). The default
    // is empty at the origin — overlays of meshes away from the origin get
    // culled. Return the actual overlay extent (world space).
    MBoundingBox boundingBox(
        const MDagPath& objPath,
        const MDagPath& cameraPath
    ) const override;

    MUserData* prepareForDraw(
        const MDagPath& objPath,
        const MDagPath& cameraPath,
        const MHWRender::MFrameContext& frameContext,
        MUserData* oldData
    ) override;

    void addUIDrawables(
        const MDagPath& objPath,
        MHWRender::MUIDrawManager& drawManager,
        const MHWRender::MFrameContext& frameContext,
        const MUserData* data
    ) override;

private:
    StukachDrawOverride(const MObject& obj);

    // Parse "0,5,12,..." string into array of ints
    static void parseIndexString(const MString& str, MIntArray& indices);

    // Get mesh dag path from the locator's inputMesh connection
    static bool getConnectedMesh(
        const MDagPath& locatorPath,
        MDagPath& meshPath
    );

    // Build triangle vertex arrays from face indices on a mesh
    static void buildFaceTriangles(
        const MDagPath& meshPath,
        const MIntArray& faceIds,
        MPointArray& outVerts,
        MPointArray& outEdges,
        float normalOffset
    );

    // Build point array from vertex indices
    static void buildVertPoints(
        const MDagPath& meshPath,
        const MIntArray& vertIds,
        MPointArray& outPoints
    );

    ~StukachDrawOverride() override;   // MUST remove the event callback

    MObject fNode;
    MCallbackId fModelEditorChangedCb;
};

#endif // STUKACH_DRAW_OVERRIDE_H
