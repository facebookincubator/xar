cmake_minimum_required(VERSION 3.5 FATAL_ERROR)

project(xar)

# Use modern C++ for everything, instruct clang (if used) to generate the
# compile_commands database.
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED on)
set(CMAKE_EXPORT_COMPILE_COMMANDS on)

# Options - build tests, etc.
option(XAR_BUILD_TESTS "Compile XAR tests" off)
option(XAR_INSTALL "Enable installation of XAR" on)

# Logging macros
set(logging_srcs xar/Logging.h xar/Logging.cpp)
add_library(Logging ${logging_srcs})

# xar helpers (easier to build as a library)
set(xarlib_srcs xar/Logging.h xar/Logging.cpp xar/XarHelpers.h xar/XarHelpers.cpp)
if(APPLE)
    list(APPEND xarlib_srcs xar/XarMacOS.cpp)
elseif(UNIX AND NOT APPLE)  # otherwise known as "Linux"
    list(APPEND xarlib_srcs xar/XarLinux.cpp)
else()
    message(FATAL_ERROR "platform is not supported")
endif()
add_library(XarHelperLib ${xarlib_srcs})
target_include_directories(XarHelperLib
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>
        $<INSTALL_INTERFACE:.>
)

# xarexec_fuse binary
set(xarexec "xarexec_fuse")
set(${xarexec} xar/XarExecFuse.cpp)
add_executable(${xarexec} xar/XarExecFuse.cpp)
target_link_libraries(${xarexec} Logging XarHelperLib)

# xarexec_fuse install
if (XAR_INSTALL)
    install(TARGETS ${xarexec}
        RUNTIME DESTINATION "bin")
endif()

# xarexec tests
if (XAR_BUILD_TESTS)
    enable_testing()
    find_package(GTest REQUIRED)
    add_executable(XarTests xar/XarHelpersTest.cpp)
    target_link_libraries(XarTests
        Logging
        XarHelperLib
        GTest::GTest
        GTest::Main
    )

    # Copy the fuse conf test files to a location in which tests will find them
    set(test_data
        fuse_conf_with_user_allow_other
        fuse_conf_without_user_allow_other
    )
    foreach(data ${test_data})
        configure_file("xar/${data}" "tools/xar/${data}" COPYONLY)
    endforeach()

    # Finally, set up the test
    gtest_add_tests(XarTests "" AUTO)
endif()
