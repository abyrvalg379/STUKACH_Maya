#include "stukachLocatorNode.h"
#include "stukachDrawOverride.h"

#include <maya/MFnPlugin.h>
#include <maya/MGlobal.h>
#include <maya/MViewport2Renderer.h>
#include <maya/MDrawRegistry.h>

// ── Registration macros (from MayaIntersectionMarker pattern) ────────────────

#define REGISTER_LOCATOR_NODE(NODE)                                             \
    {                                                                           \
        MStatus _s;                                                             \
        MFnPlugin pluginFn(obj, "STUKACH", "3.0", "Any", &_s);                 \
        if (_s) {                                                               \
            _s = pluginFn.registerNode(                                         \
                NODE::typeName,                                                 \
                NODE::id,                                                       \
                NODE::creator,                                                  \
                NODE::initialize,                                               \
                MPxNode::kLocatorNode,                                          \
                &NODE::drawDbClassification                                     \
            );                                                                  \
            if (!_s) MGlobal::displayError(                                     \
                MString("Failed to register node: ") + #NODE);                  \
        }                                                                       \
    }

#define REGISTER_DRAW_OVERRIDE(NODE, OVERRIDE)                                  \
    {                                                                           \
        MStatus _s = MHWRender::MDrawRegistry::registerDrawOverrideCreator(     \
            NODE::drawDbClassification,                                         \
            NODE::drawRegistrantId,                                             \
            OVERRIDE::creator                                                   \
        );                                                                      \
        if (!_s) MGlobal::displayError(                                         \
            MString("Failed to register draw override: ") + #OVERRIDE);         \
    }

#define DEREGISTER_LOCATOR_NODE(NODE)                                           \
    {                                                                           \
        MStatus _s;                                                             \
        MFnPlugin pluginFn(obj, "STUKACH", "3.0", "Any", &_s);                 \
        if (_s) {                                                               \
            _s = pluginFn.deregisterNode(NODE::id);                             \
            if (!_s) MGlobal::displayError(                                     \
                MString("Failed to deregister node: ") + #NODE);                \
        }                                                                       \
    }

#define DEREGISTER_DRAW_OVERRIDE(NODE, OVERRIDE)                                \
    {                                                                           \
        MStatus _s = MHWRender::MDrawRegistry::deregisterDrawOverrideCreator(   \
            NODE::drawDbClassification,                                         \
            NODE::drawRegistrantId                                              \
        );                                                                      \
        if (!_s) MGlobal::displayError(                                         \
            MString("Failed to deregister draw override: ") + #OVERRIDE);       \
    }

// ── Plugin entry points ─────────────────────────────────────────────────────

MStatus initializePlugin(MObject obj)
{
    REGISTER_LOCATOR_NODE(StukachLocatorNode);
    REGISTER_DRAW_OVERRIDE(StukachLocatorNode, StukachDrawOverride);

    MGlobal::displayInfo("[STUKACH] DrawOverride plugin loaded (v3.0)");
    return MS::kSuccess;
}

MStatus uninitializePlugin(MObject obj)
{
    DEREGISTER_DRAW_OVERRIDE(StukachLocatorNode, StukachDrawOverride);
    DEREGISTER_LOCATOR_NODE(StukachLocatorNode);

    return MS::kSuccess;
}
