#!/usr/bin/env ruby
# frozen_string_literal: true

# Ensures explicit, committed shared schemes exist for the App and
# MyKhayaWidgets targets. Without a shared scheme on disk, `xcodebuild`
# falls back to Xcode's own implicit-scheme autogeneration — which only
# happens when NO shared scheme file exists anywhere in the project at all.
# A single leftover shared scheme (e.g. a stale one from a removed target)
# is enough to silently stop that autogeneration for every other target,
# so `xcodebuild -scheme MyKhayaWidgets build` can fail with "does not
# contain a scheme named MyKhayaWidgets" purely because some OTHER stale
# .xcscheme file exists — this happened in this repo's history (a leftover
# MyKhayaWidgetsTests.xcscheme from a removed test target). Committing real
# schemes here removes the dependency on that autogeneration behaviour
# entirely, which also matters for a machine that clones the repo and runs
# `xcodebuild` without ever opening Xcode's GUI first (see
# docs/mobile/ios-shell-mac-checklist.md).
#
# Idempotent: re-running overwrites the two schemes this script owns with
# the same deterministic content; it only ever deletes a stale scheme file
# whose target no longer exists in the project.

require 'xcodeproj'

PROJECT_PATH = 'ios/App/App.xcodeproj'
SCHEMES_DIR = File.join(PROJECT_PATH, 'xcshareddata', 'xcschemes')

abort "ERROR: #{PROJECT_PATH} not found." unless File.directory?(PROJECT_PATH)

project = Xcodeproj::Project.open(PROJECT_PATH)
existing_target_names = project.targets.map(&:name)

# Remove shared scheme files whose target no longer exists in the project.
if File.directory?(SCHEMES_DIR)
  Dir.glob(File.join(SCHEMES_DIR, '*.xcscheme')).each do |scheme_path|
    scheme_name = File.basename(scheme_path, '.xcscheme')
    next if existing_target_names.include?(scheme_name)

    File.delete(scheme_path)
    puts "== Removed stale scheme (target no longer exists): #{scheme_name} =="
  end
end

def ensure_scheme(project, project_path, target_name)
  target = project.targets.find { |t| t.name == target_name }
  abort "ERROR: target '#{target_name}' not found." unless target

  scheme = Xcodeproj::XCScheme.new
  scheme.add_build_target(target)
  scheme.set_launch_target(target) if target.respond_to?(:product_type) && target.product_type == 'com.apple.product-type.application'
  scheme.save_as(project_path, target_name, true)
  puts "== Wrote shared scheme: #{target_name} =="
end

%w[App MyKhayaWidgets].each { |name| ensure_scheme(project, PROJECT_PATH, name) }
