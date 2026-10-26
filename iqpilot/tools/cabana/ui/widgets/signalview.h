#pragma once

#include <algorithm>
#include <functional>
#include <memory>
#include <set>
#include <string>
#include <utility>
#include <vector>

#include "imgui.h"
#include "imgui_internal.h"
#include "tools/cabana/core/observable.h"
#include "tools/cabana/ui/chart/chartswidget.h"
#include "tools/cabana/ui/chart/sparkline.h"
#include "tools/cabana/utils/strings.h"


class ItemValue {
public:
  ItemValue(const std::string &s) : str_(s) {}
  ItemValue(int v) : str_(std::to_string(v)) {}
  ItemValue(bool v) : str_(v ? "1" : "0") {}
  ItemValue(const ValueDescription &v) : val_desc_(v) {}
  ItemValue(const char *) = delete;
  std::string toString() const { return str_; }
  int toInt() const { return utils::toInt(str_); }
  bool toBool() const { return str_ == "1"; }
  double toDouble() const { return utils::toDouble(str_); }
  const ValueDescription &toValueDescription() const { return val_desc_; }

private:
  std::string str_;
  ValueDescription val_desc_;
};

class SignalModel {
public:
  struct Item {
    enum Type {Root, Sig, Name, Size, Node, Endian, Signed, Offset, Factor, SignalType, MultiplexValue, ExtraInfo, Unit, Comment, Min, Max, Desc };
    ~Item() { for (auto c : children) delete c; }
    inline int row() const {
      auto it = std::find(parent->children.begin(), parent->children.end(), this);
      return it != parent->children.end() ? std::distance(parent->children.begin(), it) : -1;
    }

    Type type = Type::Root;
    Item *parent = nullptr;
    std::vector<Item *> children;

    const cabana::Signal *sig = nullptr;
    std::string title;
    bool highlight = false;
    std::string sig_val = "-";
    Sparkline sparkline;
    bool expanded = false;
    bool chart_opened = false;
  };

  SignalModel();
  Item *root() const { return root_.get(); }
  const MessageId &msgId() const { return msg_id_; }
  int rowCount() const { return root_->children.size(); }
  static bool isEnabled(const Item *item);
  static bool isEditable(const Item *item);
  static bool isCheckable(const Item *item);
  std::string valueText(const Item *item) const;
  bool setData(Item *item, const ItemValue &value);
  void setMessage(const MessageId &id);
  void setFilter(const std::string &txt);
  bool saveSignal(const cabana::Signal *origin_s, cabana::Signal &s);
  int signalRow(const cabana::Signal *sig) const;

  Observable<> rowsChanged;
  Observable<> modelReset;

private:
  void insertItem(SignalModel::Item *root_item, int pos, const cabana::Signal *sig);
  void handleSignalAdded(MessageId id, const cabana::Signal *sig);
  void handleSignalUpdated(const cabana::Signal *sig);
  void handleSignalRemoved(const cabana::Signal *sig);
  void handleMsgChanged(MessageId id);
  void refresh();

  MessageId msg_id_;
  std::string filter_str_;
  std::unique_ptr<Item> root_;
  Connections connections_;
};


class ValueDescriptionDlg {
public:
  ValueDescriptionDlg(const ValueDescription &descriptions);
  bool draw();
  ValueDescription val_desc;
  std::string title;
  bool accepted = false;

private:
  void save();
  std::vector<std::pair<std::string, std::string>> table_;
  int current_row_ = -1;
  bool opened_ = false;
};

class SignalView {
public:
  SignalView(ChartsWidget *charts);
  void setMessage(const MessageId &id);
  void draw();
  static float minimumWidth();
  static float minimumHeight();
  void signalHovered(const cabana::Signal *sig);
  void updateChartState();
  void selectSignal(const cabana::Signal *sig, bool expand = false);
  bool saveSignal(const cabana::Signal *origin, cabana::Signal &s) { return model_.saveSignal(origin, s); }
  std::string whatsThis() const;

  Observable<const cabana::Signal *> highlight;
  Observable<const MessageId &, const cabana::Signal *, bool, bool> showChart;

private:
  void rowsChanged();
  void rowClicked(SignalModel::Item *item);
  static float toolBarRightWidth(const std::string &range_label);
  void updateToolBar();
  void setSparklineRange(int value);
  void handleSignalAdded(MessageId id, const cabana::Signal *sig);
  void handleSignalUpdated(const cabana::Signal *sig);
  void handleSignalRemoved(const cabana::Signal *sig);
  void updateState(const std::set<MessageId> *msgs = nullptr);

  struct DrawContext {
    ImDrawList *draw_list;
    float viewport_x;
    float width;
    float row_height;
    float name_width = 0;
    float value_column_width = 0;
    bool any_visible = false;
    bool mouse_on_row = false;
    const cabana::Signal *hovered_sig = nullptr;
  };
  void drawTree();
  bool drawItem(SignalModel::Item *item, int depth, DrawContext &ctx);
  void drawIndexWidget(SignalModel::Item *item, const ImRect &rect);
  void collapseAll();
  static float widestValueWidth(const cabana::Signal *sig);


  void paintCell(ImDrawList *painter, const ImRect &rect, const SignalModel::Item *item, int column, bool selected,
                 const std::string &text, float viewport_x) const;
  float nameColumnWidth(const SignalModel::Item *item, float widget_width, const std::string &text) const;

  void drawEditor(SignalModel::Item *item);


  void queueCommit(SignalModel::Item *item, const ItemValue &value);
  void drawValueDescriptionDlg();
  static float textWidth(const std::string &text, float font_size = 0);
  void closeEditor();
  void commitEditor();

  void drawLineEditor(SignalModel::Item *item, ImGuiInputTextCallback validator, bool take_focus);
  static ValidState validateEditor(const SignalModel::Item *item, std::string &text);

  float value_column_width_ = 0;
  bool compact_ = false;
  float name_column_width_ = 150;
  bool editor_open_on_press_ = false;


  int first_visible_row_ = -1;
  int last_visible_row_ = -1;
  const cabana::Signal *current_sig_ = nullptr;
  int current_row_ = -1;
  SignalModel::Item::Type current_type_ = SignalModel::Item::Root;
  const cabana::Signal *scroll_to_sig_ = nullptr;
  const cabana::Signal *hovered_sig_ = nullptr;
  std::function<void()> pending_action_;
  std::string sparkline_label_;
  std::string filter_edit_;
  ChartsWidget *charts_;
  std::string signal_count_lb_;

  ImVec2 button_size_ = {};

  SignalModel::Item *focus_item_ = nullptr;

  SignalModel::Item *open_item_ = nullptr;
  std::function<void()> pending_commit_;
  SignalModel::Item *editing_item_ = nullptr;
  std::string edit_text_;
  int edit_int_ = 0;
  bool editor_active_ = false;
  bool refocus_editor_ = false;
  bool enter_pressed_ = false;
  bool combo_focused_ = false;
  std::unique_ptr<ValueDescriptionDlg> desc_dlg_;
  const cabana::Signal *desc_sig_ = nullptr;
  SignalModel model_;
  Connections connections_;
};
