#!/usr/bin/env ruby
# frozen_string_literal: true

# Registers PrivacyInfo.xcprivacy (already present on disk at
# ios/App/App/PrivacyInfo.xcprivacy) as a Copy Bundle Resource on the 'App'
# target. Required because @capacitor/filesystem's Filesystem.readFile call
# (introduced for native avatar-photo selection — see ADR 0013 and
# @capacitor/filesystem's own README "Apple Privacy Manifest Requirements")
# uses a "required reason" API (NSPrivacyAccessedAPICategoryFileTimestamp);
# App Store Connect can reject a binary at upload/validation time if an app
# using such an API ships without a declaring privacy manifest. Modelled on
# add-app-target-sources.rb, but adds to the resources build phase (a
# .xcprivacy file is bundled data, not compiled Swift). Idempotent: checks
# for an existing reference/build-phase membership before adding either.

require 'xcodeproj'

PROJECT_PATH = 'ios/App/App.xcodeproj'
APP_TARGET_NAME = 'App'
FILENAME = 'PrivacyInfo.xcprivacy'

abort "ERROR: #{PROJECT_PATH} not found." unless File.directory?(PROJECT_PATH)
abort "ERROR: ios/App/App/#{FILENAME} not found on disk." unless File.exist?(File.join('ios/App/App', FILENAME))

project = Xcodeproj::Project.open(PROJECT_PATH)
app_target = project.targets.find { |t| t.name == APP_TARGET_NAME }
abort "ERROR: target '#{APP_TARGET_NAME}' not found." unless app_target

app_group = project.main_group.find_subpath(APP_TARGET_NAME, true)

existing = app_group.files.find { |f| f.path == FILENAME }
file_ref = existing || app_group.new_reference(FILENAME)

if app_target.resources_build_phase.files_references.include?(file_ref)
  puts "Already in App target's Copy Bundle Resources: #{FILENAME}"
else
  app_target.add_resources([file_ref])
  puts "Added to App target's Copy Bundle Resources: #{FILENAME}"
end

project.save
