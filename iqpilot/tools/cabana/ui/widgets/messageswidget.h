#pragma once

#include <array>
#include <cstdint>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <utility>
#include <vector>

#include "imgui.h"
#include "tools/cabana/dbc/dbcmanager.h"
#include "tools/cabana/streams/abstractstream.h"



class MessageList {
public:
  enum Column { NAME = 0, SOURCE, ADDRESS, NODE, FREQ, COUNT, DATA, COLUMN_COUNT };

  struct Item {
    MessageId id;
    std::string name;
    std::string node;
    bool operator==(const Item &other) const { return id == other.id && name == other.name && node == other.node; }
  };

  MessageList();
  void sort(int column, ImGuiSortDirection order);
  void setFilters(const std::map<int, std::string> &filters);
  void showInactiveMessages(bool show);
  bool filterAndSort();

  std::vector<Item> items;
  bool show_inactive_messages = true;
  Observable<> changed;

private:
  void msgsReceived(const std::set<MessageId> *new_msgs, bool has_new_ids);
  void dbcModified();
  void sortItems(std::vector<Item> &list);
  bool match(const Item &item);

  std::map<int, std::string> filters_;
  std::set<MessageId> dbc_messages_;
  int sort_column_ = NAME;
  ImGuiSortDirection sort_order_ = ImGuiSortDirection_Ascending;
  int sort_threshold_ = 0;
  Connections connections_;
};

class MessagesWidget {
public:
  MessagesWidget();
  void draw();
  void selectMessage(const MessageId &message_id);
  void suppressHighlighted(bool from_suppress_add = false);
  const std::string &title() const { return title_; }
  std::string whatsThis() const;

  Observable<const MessageId &> msgSelectionChanged;

private:
  void drawToolBar();
  void drawTable();
  void drawHeader();
  void drawRow(int row);
  void drawContextMenu();
  void handleKeys();
  void setCurrentRow(int row);
  void updateBytesSectionSize();
  void updateTitle();
  void setMultiLineBytes(bool multi);

  MessageList list_;
  std::optional<MessageId> current_msg_id_;
  int current_row_ = -1;
  bool scroll_to_current_ = false;
  int bytes_section_bytes_ = 8;
  float fixed_columns_width_ = 0;
  bool has_scrollbar_y_ = false;
  int visible_rows_ = 1;
  std::array<std::string, MessageList::COLUMN_COUNT> filters_;
  std::array<bool, MessageList::COLUMN_COUNT> hidden_ = {};
  std::array<int, MessageList::COLUMN_COUNT> display_order_;
  std::vector<std::pair<int, bool>> pending_hidden_;
  bool header_menu_requested_ = false;
  std::string suppress_clear_text_;
  bool suppress_clear_enabled_ = false;
  std::string title_ = "MESSAGES";
  Connections connections_;
};
