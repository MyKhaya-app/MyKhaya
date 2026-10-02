#!/usr/bin/env ruby
# frozen_string_literal: true

# Adds the local MyKhayaWidgetCore Swift Package (apps/ios-shell/native/
# WidgetCore/) as a dependency of both the App target and the MyKhayaWidgets
# extension target, so both can `import MyKhayaWidgetCore`. Invoked by
# install-widget-sources.sh, alongside setup-widget-extension.rb.
#
# WHY a local package, not more loose Swift files copied into each target
# (the previous approach for WidgetSnapshot.swift/WidgetSnapshotStore.swift):
# an app extension's own compiled code cannot be an XCTest host — a hosted
# test bundle (TEST_HOST pointed at the built .appex) and a logic-only test
# bundle both fail identically with "symbol(s) not found for architecture
# arm64" when trying to link against MyKhayaWidgets.appex. A local Swift
# Package's product is a static library that compiles into each importing
# target AND has its own test target that `swift test`/`xcodebuild test`
# can run directly, independent of either app target. See
# docs/mobile/ios-widgets.md.
#
# Idempotent: finds the existing XCLocalSwiftPackageReference by its
# relative_path and the existing XCSwiftPackageProductDependency by product
# name before creating either, so re-running after `git pull` never
# duplicates the package reference, the product dependency, or the
# Frameworks build phase entry.

require 'xcodeproj'

PROJECT_PATH = 'ios/App/App.xcodeproj'
PACKAGE_NAME = 'MyKhayaWidgetCore'
# Relative to the directory containing App.xcodeproj (ios/App/), matching
# how Xcode itself resolves a local package reference's relative_path.
PACKAGE_RELATIVE_PATH = '../../native/WidgetCore'
TARGET_NAMES = %w[App MyKhayaWidgets].freeze

abort "ERROR: #{PROJECT_PATH} not found." unless File.directory?(PROJECT_PATH)

srcroot = File.dirname(File.expand_path(PROJECT_PATH))
package_absolute_path = File.expand_path(PACKAGE_RELATIVE_PATH, srcroot)
unless File.exist?(File.join(package_absolute_path, 'Package.swift'))
  abort "ERROR: no Package.swift found at #{package_absolute_path} (resolved from #{PACKAGE_RELATIVE_PATH} relative to #{srcroot})."
end

project = Xcodeproj::Project.open(PROJECT_PATH)

# A previous approach tried testing MyKhayaWidgets logic via a hosted
# XCTest target (TEST_HOST pointed at the built .appex). That's not
# possible — an app extension isn't an independently linkable XCTest host —
# so it compiled but always failed at link time with 0 tests ever run.
# MyKhayaWidgetCore's own package test target replaces it entirely; remove
# the stale target idempotently so a Mac that created it before this script
# existed self-heals on rerun.
stale_test_target = project.targets.find { |t| t.name == 'MyKhayaWidgetsTests' }
if stale_test_target
  stale_test_target.remove_from_project
  puts '== Removed stale MyKhayaWidgetsTests target (superseded by the MyKhayaWidgetCore package test target) =='
end

package_ref = project.root_object.package_references.find do |ref|
  ref.is_a?(Xcodeproj::Project::Object::XCLocalSwiftPackageReference) && ref.relative_path == PACKAGE_RELATIVE_PATH
end

if package_ref
  puts "== #{PACKAGE_NAME} local package reference already present =="
else
  package_ref = project.new(Xcodeproj::Project::Object::XCLocalSwiftPackageReference)
  package_ref.relative_path = PACKAGE_RELATIVE_PATH
  project.root_object.package_references << package_ref
  puts "== Added #{PACKAGE_NAME} local package reference (#{PACKAGE_RELATIVE_PATH}) =="
end

TARGET_NAMES.each do |target_name|
  target = project.targets.find { |t| t.name == target_name }
  abort "ERROR: target '#{target_name}' not found in #{PROJECT_PATH}." unless target

  existing_dependency = target.package_product_dependencies.find { |dep| dep.product_name == PACKAGE_NAME }
  if existing_dependency
    puts "Already linked: #{target_name} -> #{PACKAGE_NAME}"
    next
  end

  product_dependency = project.new(Xcodeproj::Project::Object::XCSwiftPackageProductDependency)
  product_dependency.package = package_ref
  product_dependency.product_name = PACKAGE_NAME
  target.package_product_dependencies << product_dependency

  # package_product_dependencies alone declares the dependency graph edge;
  # Xcode also needs a PBXBuildFile with product_ref set, filed under the
  # target's Frameworks build phase, for the actual link step to happen.
  build_file = project.new(Xcodeproj::Project::Object::PBXBuildFile)
  build_file.product_ref = product_dependency
  target.frameworks_build_phase.files << build_file

  puts "Linked: #{target_name} -> #{PACKAGE_NAME}"
end

project.save

puts ''
puts "== Done. #{PACKAGE_NAME} is now a dependency of: #{TARGET_NAMES.join(', ')} =="
