ThisBuild / version := "0.1.0-SNAPSHOT"
ThisBuild / organization     := "%ORGANIZATION%"
ThisBuild / scalaVersion := "2.12.15"

val chiselVersion = "3.5.0"

lazy val root = (project in file("."))
  .settings(
    name := "MemBox2S",
    libraryDependencies ++= Seq(
      "edu.berkeley.cs" %% "chisel3" % chiselVersion,
      "edu.berkeley.cs" %% "chiseltest" % "0.5.0" % "test"
    ),
    scalacOptions ++= Seq(
      "-language:reflectiveCalls",
      "-deprecation",
      "-feature",
      "-Xcheckinit",
    ),
    addCompilerPlugin("edu.berkeley.cs" % "chisel3-plugin" % chiselVersion cross CrossVersion.full),
  )
