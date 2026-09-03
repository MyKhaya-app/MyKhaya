#!/usr/bin/env ruby
# frozen_string_literal: true

# Adds the widget-bridge Swift files copied into ios/App/App/ by
# install-widget-sources.sh to the 'App' target's source build phase.
# Separate from setup-widget-extension.rb (which owns the MyKhayaWidgets
# target) because these four files belong to the *main app* target instead.
# Idempotent: checks for an existing reference before adding.

require 'xcodeproj'

PROJECT_PATH = 'ios/App/App.xcodeproj'
APP_TARGET_NAME = 'App'
FILES = %w[
  WidgetBridgePlugin.swift
  MainViewController.swift
  WidgetSnapshot.swift
  WidgetSnapshotStore.swift
].freeze

abort "ERROR: #{PROJECT_PATH} not found." unless File.directory?(PROJECT_PATH)

project = Xcodeproj::Project.open(PROJECT_PATH)
app_target = project.targets.find { |t| t.name == APP_TARGET_NAME }
abort "ERROR: target '#{APP_TARGET_NAME}' not found." unless app_target

app_group = project.main_group.find_subpath(APP_TARGET_NAME, true)

FILES.each do |filename|
  existing = app_group.files.find { |f| f.path == filename }
  file_ref = existing || app_group.new_reference(filename)
  if app_target.source_build_phase.files_references.include?(file_ref)
    puts "Already in App target: #{filename}"
  else
    app_target.add_file_references([file_ref])
    puts "Added to App target: #{filename}"
  end
end

project.save
