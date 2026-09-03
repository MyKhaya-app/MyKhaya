#!/usr/bin/env ruby
# frozen_string_literal: true

# Creates/updates the MyKhayaWidgets Widget Extension target inside the
# Mac-generated ios/App/App.xcodeproj. Invoked by
# scripts/install-widget-sources.sh — never run this directly unless you're
# debugging it.
#
# Why the `xcodeproj` gem and not hand-editing project.pbxproj: a widget
# extension needs a genuinely new Xcode target (its own Info.plist, source
# set, entitlements, build settings, embed-in-parent build phase) — the
# same category of change CocoaPods' own `pod install` makes to
# project.pbxproj on every run. `xcodeproj` is the gem CocoaPods itself is
# built on; anyone who has run `brew install cocoapods` per
# docs/mobile/ios-shell-mac-checklist.md already has it (`gem list
# xcodeproj` confirms). This is judged safer and more reliable than direct
# pbxproj text substitution, which the task's own instructions warn against.
#
# Idempotent: safe to re-run after `git pull` picks up new/changed widget
# sources. Finds the existing MyKhayaWidgets target by name rather than
# creating a duplicate; re-adds only files/settings that are missing.

require 'xcodeproj'
require 'fileutils'

PROJECT_PATH = 'ios/App/App.xcodeproj'
APP_TARGET_NAME = 'App'
WIDGET_TARGET_NAME = 'MyKhayaWidgets'
APP_BUNDLE_ID = 'app.mykhaya.mobile'
WIDGET_BUNDLE_ID = "#{APP_BUNDLE_ID}.widgets"
APP_GROUP_ID = 'group.app.mykhaya.mobile'
# Conservative floor — see native/widgets/Timeline/NextEventProvider.swift's
# deployment-target comment. Raise this only after confirming the actual
# generated project's own main-target minimum on the Mac (Step 0 below).
WIDGET_DEPLOYMENT_TARGET = '16.0'

unless File.directory?(PROJECT_PATH)
  abort "ERROR: #{PROJECT_PATH} not found. Run this from apps/ios-shell after `npx cap add ios`."
end

project = Xcodeproj::Project.open(PROJECT_PATH)

app_target = project.targets.find { |t| t.name == APP_TARGET_NAME }
abort "ERROR: main app target '#{APP_TARGET_NAME}' not found in #{PROJECT_PATH}" unless app_target

main_deployment_target = app_target.build_configurations.first&.build_settings&.dig('IPHONEOS_DEPLOYMENT_TARGET')
puts "== Main app target IPHONEOS_DEPLOYMENT_TARGET: #{main_deployment_target.inspect} =="
puts "   (widget extension will use #{WIDGET_DEPLOYMENT_TARGET} — adjust WIDGET_DEPLOYMENT_TARGET above if this is lower)"

widget_target = project.targets.find { |t| t.name == WIDGET_TARGET_NAME }

if widget_target
  puts "== MyKhayaWidgets target already exists — updating in place =="
else
  puts "== Creating MyKhayaWidgets target =="
  widget_target = project.new_target(
    :app_extension,
    WIDGET_TARGET_NAME,
    :ios,
    WIDGET_DEPLOYMENT_TARGET,
    project.main_group,
    :dynamic
  )
end

# --- Group + source files -------------------------------------------------

widgets_group = project.main_group.find_subpath(WIDGET_TARGET_NAME, true)
widgets_group.set_source_tree('SOURCE_ROOT')

source_root = File.expand_path("#{WIDGET_TARGET_NAME}", Dir.pwd)
FileUtils.mkdir_p(source_root)

def add_swift_files(project, group, target, dir, seen_paths)
  Dir.glob(File.join(dir, '**', '*.swift')).sort.each do |absolute_path|
    relative = Pathname.new(absolute_path).relative_path_from(Pathname.new(Dir.pwd)).to_s
    next if seen_paths.include?(relative)

    file_ref = group.files.find { |f| File.basename(f.path.to_s) == File.basename(absolute_path) } ||
               group.new_reference(absolute_path)
    unless target.source_build_phase.files_references.include?(file_ref)
      target.add_file_references([file_ref])
    end
    seen_paths << relative
  end
end

# Prunes file references for .swift files that no longer exist on disk —
# e.g. WidgetSnapshot.swift/WidgetSnapshotStore.swift, extracted into the
# MyKhayaWidgetCore package and deleted from native/widgets/Shared/.
# add_swift_files only ever adds; without this, a moved/deleted source
# leaves a stale PBXFileReference that fails the build with "Build input
# files cannot be found" the next time MyKhayaWidgets/ is rsynced from
# native/widgets/ (rsync --delete removes the copy, but never touches
# project.pbxproj).
def prune_missing_swift_files(group, target)
  group.files.select { |f| f.path.to_s.end_with?('.swift') }.each do |file_ref|
    absolute_path = file_ref.real_path.to_s
    next if File.exist?(absolute_path)

    target.source_build_phase.remove_file_reference(file_ref)
    file_ref.remove_from_project
    puts "== Removed stale file reference (source no longer exists): #{absolute_path} =="
  end
end

seen = []
add_swift_files(project, widgets_group, widget_target, source_root, seen)
prune_missing_swift_files(widgets_group, widget_target)
puts "== Widget source files in target: #{seen.size} =="

# --- Info.plist for the extension ----------------------------------------

widget_info_plist_path = File.join(source_root, 'Info.plist')
unless File.exist?(widget_info_plist_path)
  File.write(widget_info_plist_path, <<~PLIST)
    <?xml version="1.0" encoding="UTF-8"?>
    <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
    <plist version="1.0">
    <dict>
    	<key>CFBundleDisplayName</key>
    	<string>MyKhaya Widgets</string>
    	<key>CFBundleExecutable</key>
    	<string>$(EXECUTABLE_NAME)</string>
    	<key>CFBundleIdentifier</key>
    	<string>$(PRODUCT_BUNDLE_IDENTIFIER)</string>
    	<key>CFBundleName</key>
    	<string>$(PRODUCT_NAME)</string>
    	<key>CFBundleShortVersionString</key>
    	<string>$(MARKETING_VERSION)</string>
    	<key>CFBundleVersion</key>
    	<string>$(CURRENT_PROJECT_VERSION)</string>
    	<key>NSExtension</key>
    	<dict>
    		<key>NSExtensionPointIdentifier</key>
    		<string>com.apple.widgetkit-extension</string>
    	</dict>
    </dict>
    </plist>
  PLIST
  puts "== Wrote #{widget_info_plist_path} =="
end

# Self-heal a widget Info.plist written by an older version of this script
# that omitted CFBundleExecutable/CFBundleName — `xcodebuild build` succeeds
# either way (nothing about compiling/linking needs them), but a real
# install (simctl, and presumably App Store) rejects the resulting .appex:
# "missing or invalid CFBundleExecutable" / "does not have a CFBundleName
# key with a non-zero length string value". Verified by actually attempting
# `simctl install`, not assumed from a successful build.
info_plist = Xcodeproj::Plist.read_from_path(widget_info_plist_path)
changed = false
{ 'CFBundleExecutable' => '$(EXECUTABLE_NAME)', 'CFBundleName' => '$(PRODUCT_NAME)' }.each do |key, value|
  next if info_plist[key]

  info_plist[key] = value
  changed = true
  puts "== Added missing #{key} to #{widget_info_plist_path} =="
end
Xcodeproj::Plist.write_to_path(info_plist, widget_info_plist_path) if changed

# --- Entitlements for the extension (App Group only — no APNs here) ------

widget_entitlements_path = File.join(source_root, 'MyKhayaWidgets.entitlements')
unless File.exist?(widget_entitlements_path)
  File.write(widget_entitlements_path, <<~PLIST)
    <?xml version="1.0" encoding="UTF-8"?>
    <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
    <plist version="1.0">
    <dict>
    	<key>com.apple.security.application-groups</key>
    	<array>
    		<string>#{APP_GROUP_ID}</string>
    	</array>
    </dict>
    </plist>
  PLIST
  puts "== Wrote #{widget_entitlements_path} =="
end

# --- Build settings --------------------------------------------------------

# CODE_SIGN_ENTITLEMENTS/INFOPLIST_FILE are resolved by Xcode relative to
# SRCROOT (the directory containing the .xcodeproj, i.e. ios/App/) — NOT
# relative to Dir.pwd (apps/ios-shell/) where this script runs and where
# source_root actually lives. A bare "MyKhayaWidgets/..." string previously
# left both paths pointing at a nonexistent ios/App/MyKhayaWidgets/, which
# Xcode surfaced as "could not be opened" on the entitlements file (and would
# equally have failed to find Info.plist). Compute the real relative path
# instead of hardcoding "../../" so this stays correct if nesting changes.
srcroot = File.dirname(File.expand_path(PROJECT_PATH))
entitlements_relative = Pathname.new(widget_entitlements_path).relative_path_from(Pathname.new(srcroot)).to_s
info_plist_relative = Pathname.new(widget_info_plist_path).relative_path_from(Pathname.new(srcroot)).to_s

widget_target.build_configurations.each do |config|
  # Without this, PRODUCT_NAME is unset and the built extension's filename
  # collapses to a bare ".appex" — indistinguishable from the main app
  # target's own product, which xcodebuild rejects as "Multiple commands
  # produce '.../.appex'". $(TARGET_NAME) matches every other target's
  # convention in this project (see the App target's own PRODUCT_NAME).
  config.build_settings['PRODUCT_NAME'] = '$(TARGET_NAME)'
  config.build_settings['PRODUCT_BUNDLE_IDENTIFIER'] = WIDGET_BUNDLE_ID
  config.build_settings['IPHONEOS_DEPLOYMENT_TARGET'] = WIDGET_DEPLOYMENT_TARGET
  config.build_settings['CODE_SIGN_ENTITLEMENTS'] = entitlements_relative
  config.build_settings['INFOPLIST_FILE'] = info_plist_relative
  config.build_settings['SWIFT_VERSION'] = '5.0'
  config.build_settings['TARGETED_DEVICE_FAMILY'] = '1'
  config.build_settings['SKIP_INSTALL'] = 'YES'
  # Matches the main app target's own automatic-signing convention (see
  # docs/mobile/ios-shell-mac-checklist.md Step 4) — do not hardcode a Team.
  config.build_settings['CODE_SIGN_STYLE'] = 'Automatic'
end

# --- App Group entitlement on the MAIN app target too ---------------------
# Preserve every existing entitlement (aps-environment above all — see
# docs/mobile/ios-widgets.md's explicit before/after diff requirement) and
# only add com.apple.security.application-groups if missing.

# The App target uses separate per-configuration entitlements files
# (AppDebug.entitlements / AppRelease.entitlements) rather than a single
# App.entitlements — see docs/mobile/ios-shell-mac-checklist.md. Both must
# get the App Group; a single "App.entitlements" path would silently never
# match either real file.
%w[ios/App/App/AppDebug.entitlements ios/App/App/AppRelease.entitlements].each do |app_entitlements_path|
  if File.exist?(app_entitlements_path)
    plist = Xcodeproj::Plist.read_from_path(app_entitlements_path)
    groups = plist['com.apple.security.application-groups'] || []
    unless groups.include?(APP_GROUP_ID)
      groups << APP_GROUP_ID
      plist['com.apple.security.application-groups'] = groups
      Xcodeproj::Plist.write_to_path(plist, app_entitlements_path)
      puts "== Added App Group entitlement to #{app_entitlements_path} =="
    end
    aps_present = plist.key?('aps-environment')
    puts "== aps-environment present in #{app_entitlements_path} after edit: #{aps_present} =="
    unless aps_present
      puts "WARNING: aps-environment missing from #{app_entitlements_path} — APNs entitlement may have been lost or was never present. Investigate before archiving."
    end
  else
    puts "WARNING: #{app_entitlements_path} not found — cannot add the App Group entitlement to the main app target. Add it manually in Xcode: App target -> Signing & Capabilities -> + Capability -> App Groups -> #{APP_GROUP_ID}."
  end
end

# --- Embed the extension in the main app target ---------------------------

embed_phase = app_target.copy_files_build_phases.find { |p| p.name == 'Embed App Extensions' } ||
              app_target.new_copy_files_build_phase('Embed App Extensions')
embed_phase.symbol_dst_subfolder_spec = :plug_ins

widget_product = widget_target.product_reference
already_embedded = embed_phase.files.any? { |f| f.file_ref == widget_product }
unless already_embedded
  build_file = embed_phase.add_file_reference(widget_product)
  build_file.settings = { 'ATTRIBUTES' => ['RemoveHeadersOnCopy'] }
  puts '== Embedded MyKhayaWidgets.appex in the App target =='
end

app_target.add_dependency(widget_target) unless app_target.dependencies.any? { |d| d.target == widget_target }

project.save

puts ''
puts '== Done. Open ios/App/App.xcodeproj in Xcode and confirm: =='
puts '   - MyKhayaWidgets target exists with a Signing & Capabilities tab showing App Groups'
puts '   - App target also shows the App Groups capability, still alongside Push Notifications'
puts '   - Product > Scheme includes MyKhayaWidgets (Xcode adds this automatically for a new target)'
puts '   - Build the App scheme once; a target-creation issue here usually surfaces as a clear Xcode error, not a silent failure'
