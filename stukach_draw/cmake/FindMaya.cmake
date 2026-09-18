# FindMaya.cmake — locates Maya SDK and sets up plugin build.
# Based on MayaIntersectionMarker's FindMaya.cmake, simplified for Maya 2025+.

# Maya install path
if(NOT DEFINED MAYA_VERSION)
    set(MAYA_VERSION 2025)
endif()

set(MAYA_INSTALL_BASE_PATH "C:/Program Files/Autodesk/Maya${MAYA_VERSION}")
set(MAYA_LOCATION "${MAYA_INSTALL_BASE_PATH}")

# Headers
find_path(MAYA_INCLUDE_DIR
    NAMES maya/MTypes.h maya/MPxNode.h
    PATHS "${MAYA_LOCATION}/include"
    NO_DEFAULT_PATH
)

# Libraries
set(_MAYA_LIBS OpenMaya OpenMayaAnim OpenMayaFX OpenMayaRender OpenMayaUI Foundation)
set(MAYA_LIBRARIES "")

foreach(_lib ${_MAYA_LIBS})
    find_library(MAYA_${_lib}_LIBRARY
        NAMES ${_lib}
        PATHS "${MAYA_LOCATION}/lib"
        NO_DEFAULT_PATH
    )
    if(MAYA_${_lib}_LIBRARY)
        list(APPEND MAYA_LIBRARIES "${MAYA_${_lib}_LIBRARY}")
    endif()
endforeach()

# clew (OpenCL wrapper, needed by some Maya versions)
find_library(MAYA_clew_LIBRARY
    NAMES clew
    PATHS "${MAYA_LOCATION}/lib"
    NO_DEFAULT_PATH
)
if(MAYA_clew_LIBRARY)
    list(APPEND MAYA_LIBRARIES "${MAYA_clew_LIBRARY}")
endif()

include(FindPackageHandleStandardArgs)
find_package_handle_standard_args(Maya
    REQUIRED_VARS MAYA_INCLUDE_DIR MAYA_LIBRARIES
)

# MAYA_PLUGIN() — set up a target as a Maya plugin
function(MAYA_PLUGIN _target)
    # Windows: .mll extension, export initializePlugin/uninitializePlugin
    if(WIN32)
        set_target_properties(${_target} PROPERTIES
            SUFFIX ".mll"
            PREFIX ""
        )
        target_link_options(${_target} PRIVATE
            "/export:initializePlugin"
            "/export:uninitializePlugin"
        )
    elseif(APPLE)
        set_target_properties(${_target} PROPERTIES
            SUFFIX ".bundle"
            PREFIX ""
        )
    else()
        set_target_properties(${_target} PROPERTIES
            SUFFIX ".so"
            PREFIX ""
        )
    endif()

    # Maya-specific defines
    target_compile_definitions(${_target} PRIVATE
        REQUIRE_IOSTREAM
        _BOOL
        MAYA_VERSION=${MAYA_VERSION}
    )

    # Suppress MSVC warnings
    if(MSVC)
        target_compile_options(${_target} PRIVATE /W3 /wd4251 /wd4275)
    endif()
endfunction()
